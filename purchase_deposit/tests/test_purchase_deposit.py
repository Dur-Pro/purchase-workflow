# Copyright 2019 Elico Corp, Dominique K. <dominique.k@elico-corp.com.sg>
# Copyright 2019 Ecosoft Co., Ltd., Kitti U. <kittiu@ecosoft.co.th>
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import Form, TransactionCase


class TestPurchaseDeposit(TransactionCase):
    def setUp(self):
        super(TestPurchaseDeposit, self).setUp()
        self.product_model = self.env["product.product"]
        self.account_model = self.env["account.account"]
        self.invoice_model = self.env["account.move"]
        self.default_model = self.env["ir.default"]

        # Create Deposit Account
        self.account_deposit = self.account_model.create(
            {
                "name": "Purchase Deposit",
                "code": "11620",
                "user_type_id": self.env.ref(
                    "account.data_account_type_current_assets"
                ).id,
            }
        )
        # Create products:
        p1 = self.product1 = self.product_model.create(
            {
                "name": "Test Product 1",
                "type": "service",
                "default_code": "PROD1",
                "purchase_method": "purchase",
            }
        )
        self.po = self.env["purchase.order"].create(
            {
                "partner_id": self.ref("base.res_partner_3"),
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": p1.id,
                            "product_uom": p1.uom_id.id,
                            "name": p1.name,
                            "price_unit": 100.0,
                            "date_planned": fields.Datetime.now(),
                            "product_qty": 42.0,
                        },
                    )
                ],
            }
        )
        # Create product with control policy = on received quantities
        p2 = self.product2 = self.product_model.create(
            {
                "name": "Test Product 2",
                "type": "service",
                "default_code": "PROD2",
                "purchase_method": "receive",  # For testing partial return
            }
        )
        self.po2 = self.env["purchase.order"].create(
            {
                "partner_id": self.ref("base.res_partner_3"),
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": p2.id,
                            "product_uom": p2.uom_id.id,
                            "name": p2.name,
                            "price_unit": 100.0,
                            "date_planned": fields.Datetime.now(),
                            "product_qty": 10,
                            "qty_received": 1,  # Partial received
                        },
                    )
                ],
            }
        )

    def test_create_deposit_invoice(self):
        self.assertEqual(len(self.po.order_line), 1)
        # We create invoice from expense
        ctx = {
            "active_id": self.po.id,
            "active_ids": [self.po.id],
            "active_model": "purchase.order",
            "create_bills": True,
        }
        CreateDeposit = self.env["purchase.advance.payment.inv"]
        self.po.button_confirm()
        with Form(CreateDeposit.with_context(**ctx)) as f:
            f.advance_payment_method = "percentage"
            f.deposit_account_id = self.account_deposit
        wizard = f.save()
        wizard.amount = 10.0  # 10%
        wizard.create_invoices()
        # New Purchase Deposit is created automatically
        deposit_id = self.default_model.sudo().get(
            "purchase.advance.payment.inv", "purchase_deposit_product_id"
        )
        deposit = self.product_model.browse(deposit_id)
        self.assertEqual(deposit.name, "Purchase Deposit")
        # 1 Deposit Invoice is created
        self.assertRecordValues(
            self.po.invoice_ids.invoice_line_ids,
            [
                {
                    "product_id": deposit.id,
                    "price_unit": 420.0,
                    "name": "Deposit Payment",
                }
            ],
        )
        # On Purchase Order, there will be new deposit line create
        self.assertRecordValues(
            self.po.order_line,
            [
                {
                    "product_id": self.product1.id,
                    "price_unit": 100.0,
                    "is_deposit": False,
                },
                {"product_id": deposit.id, "price_unit": 420.0, "is_deposit": True},
            ],
        )
        # On Purchase Order, create normal billing with advance return option = Full
        res = self.po.with_context(
            create_bill=True, advance_deduct_option="full"
        ).action_create_invoice()
        invoice = self.invoice_model.browse(res["res_id"])
        self.assertRecordValues(
            invoice.invoice_line_ids,
            [
                {"product_id": self.product1.id, "price_unit": 100.0, "quantity": 42},
                {"product_id": deposit.id, "price_unit": 420.0, "quantity": -1},
            ],
        )

    def test_create_deposit_invoice_partial_deduct(self):
        self.assertEqual(len(self.po2.order_line), 1)
        # We create invoice from expense
        ctx = {
            "active_id": self.po2.id,
            "active_ids": [self.po2.id],
            "active_model": "purchase.order",
            "create_bills": True,
        }
        CreateDeposit = self.env["purchase.advance.payment.inv"]
        self.po2.button_confirm()
        with Form(CreateDeposit.with_context(**ctx)) as f:
            f.advance_payment_method = "percentage"
            f.deposit_account_id = self.account_deposit
        wizard = f.save()
        wizard.amount = 10.0  # 10%
        wizard.create_invoices()
        # New Purchase Deposit is created automatically
        deposit_id = self.default_model.sudo().get(
            "purchase.advance.payment.inv", "purchase_deposit_product_id"
        )
        deposit = self.product_model.browse(deposit_id)
        self.assertEqual(deposit.name, "Purchase Deposit")
        # 1 Deposit Invoice is created
        self.assertRecordValues(
            self.po2.invoice_ids.invoice_line_ids,
            [
                {
                    "product_id": deposit.id,
                    "price_unit": 100.0,
                    "name": "Deposit Payment",
                }
            ],
        )
        # On Purchase Order, there will be new deposit line create
        self.assertRecordValues(
            self.po2.order_line,
            [
                {
                    "product_id": self.product2.id,
                    "price_unit": 100.0,
                    "is_deposit": False,
                },
                {"product_id": deposit.id, "price_unit": 100.0, "is_deposit": True},
            ],
        )
        # On Purchase Order, create normal billing with advance return option = proportional
        res = self.po2.with_context(
            create_bill=True, advance_deduct_option="proportional"
        ).action_create_invoice()
        invoice = self.invoice_model.browse(res["res_id"])
        self.assertRecordValues(
            invoice.invoice_line_ids,
            [
                {"product_id": self.product2.id, "price_unit": 100.0, "quantity": 1},
                {"product_id": deposit.id, "price_unit": 100.0, "quantity": -0.1},
            ],
        )

    def test_create_deposit_invoice_exception_1(self):
        """This test focus on exception cases, when create deposit invoice,
        1. This action is allowed only in Purchase Order sate
        2. The value of the deposit must be positive
        3. For type percentage, The percentage of the deposit must <= 100
        """
        self.assertEqual(len(self.po.order_line), 1)
        # We create invoice from expense
        ctx = {
            "active_id": self.po.id,
            "active_ids": [self.po.id],
            "active_model": "purchase.order",
            "create_bills": True,
        }
        CreateDeposit = self.env["purchase.advance.payment.inv"]
        # 1. This action is allowed only in Purchase Order sate
        with self.assertRaises(UserError):
            Form(CreateDeposit.with_context(**ctx))  # Initi wizard
        self.po.button_confirm()
        self.assertEqual(self.po.state, "purchase")
        # 2. The value of the deposit must be positive
        f = Form(CreateDeposit.with_context(**ctx))
        f.advance_payment_method = "fixed"
        f.amount = 0.0
        f.deposit_account_id = self.account_deposit
        wizard = f.save()
        with self.assertRaises(UserError):
            wizard.create_invoices()
        # 3. For type percentage, The percentage of the deposit must <= 100
        wizard.advance_payment_method = "percentage"
        wizard.amount = 101.0
        with self.assertRaises(UserError):
            wizard.create_invoices()
        wizard.amount = 10

    def test_create_deposit_invoice_exception_2(self):
        """This test focus on exception cases, when create deposit invoice,
        4. Purchase Deposit Product's purchase_method != purchase
        """
        self.assertEqual(len(self.po.order_line), 1)
        # We create invoice from expense
        ctx = {
            "active_id": self.po.id,
            "active_ids": [self.po.id],
            "active_model": "purchase.order",
            "create_bills": True,
        }
        CreateDeposit = self.env["purchase.advance.payment.inv"]
        self.po.button_confirm()
        self.assertEqual(self.po.state, "purchase")
        f = Form(CreateDeposit.with_context(**ctx))
        f.advance_payment_method = "percentage"
        f.amount = 101.0
        f.deposit_account_id = self.account_deposit
        wizard = f.save()
        # 4. Purchase Deposit Product's purchase_method != purchase
        deposit_id = self.default_model.sudo().get(
            "purchase.advance.payment.inv", "purchase_deposit_product_id"
        )
        deposit = self.product_model.browse(deposit_id)
        deposit.purchase_method = "receive"
        wizard.purchase_deposit_product_id = deposit
        with self.assertRaises(UserError):
            wizard.create_invoices()

    def test_create_deposit_invoice_exception_3(self):
        """This test focus on exception cases, when create deposit invoice,
        5. Purchase Deposit Product's type != service
        """
        self.assertEqual(len(self.po.order_line), 1)
        # We create invoice from expense
        ctx = {
            "active_id": self.po.id,
            "active_ids": [self.po.id],
            "active_model": "purchase.order",
            "create_bills": True,
        }
        CreateDeposit = self.env["purchase.advance.payment.inv"]
        self.po.button_confirm()
        self.assertEqual(self.po.state, "purchase")
        f = Form(CreateDeposit.with_context(**ctx))
        f.advance_payment_method = "percentage"
        f.amount = 101.0
        f.deposit_account_id = self.account_deposit
        wizard = f.save()
        deposit_id = self.default_model.sudo().get(
            "purchase.advance.payment.inv", "purchase_deposit_product_id"
        )
        deposit = self.product_model.browse(deposit_id)
        # 5. Purchase Deposit Product's type != service
        deposit.type = "consu"
        with self.assertRaises(UserError):
            wizard.create_invoices()
