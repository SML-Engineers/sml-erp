import type { ReactNode } from "react";
import { Route, Routes } from "react-router";

import type { CurrentUser } from "./api/auth";
import AuthGate from "./components/AuthGate";
import AppLayout, { useMe } from "./layout/AppLayout";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import CostingRatesPage from "./pages/CostingRatesPage";
import CustomersPage from "./pages/CustomersPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import BankAccountsPage from "./pages/BankAccountsPage";
import ChartOfAccountsPage from "./pages/ChartOfAccountsPage";
import DirectorPage from "./pages/DirectorPage";
import DeletedVouchersPage from "./pages/DeletedVouchersPage";
import AmendmentsPage from "./pages/AmendmentsPage";
import CancellationsPage from "./pages/CancellationsPage";
import VoucherReportsPage from "./pages/VoucherReportsPage";
import AdvancePage from "./pages/AdvancePage";
import CreditHoldsPage from "./pages/CreditHoldsPage";
import PayablesPage from "./pages/PayablesPage";
import SupplierStatementPage from "./pages/SupplierStatementPage";
import SupplierStatementsPage from "./pages/SupplierStatementsPage";
import ReceiptPage from "./pages/ReceiptPage";
import ReceivablesPage from "./pages/ReceivablesPage";
import StatementPage from "./pages/StatementPage";
import ReceiptsPage from "./pages/ReceiptsPage";
import AdvancesPage from "./pages/AdvancesPage";
import PaymentsPage from "./pages/PaymentsPage";
import ProformaPage from "./pages/ProformaPage";
import ProformasPage from "./pages/ProformasPage";
import SalesOrderPage from "./pages/SalesOrderPage";
import SalesReportsPage from "./pages/SalesReportsPage";
import CreditNotePage from "./pages/CreditNotePage";
import CreditNotesPage from "./pages/CreditNotesPage";
import DeliveryNotePage from "./pages/DeliveryNotePage";
import DeliveryNotesPage from "./pages/DeliveryNotesPage";
import FinancialReportsPage from "./pages/FinancialReportsPage";
import GoodsReceiptPage from "./pages/GoodsReceiptPage";
import GoodsReceiptsPage from "./pages/GoodsReceiptsPage";
import InspectionPage from "./pages/InspectionPage";
import InspectionPlansPage from "./pages/InspectionPlansPage";
import InspectionsPage from "./pages/InspectionsPage";
import ItemsPage from "./pages/ItemsPage";
import StockPage from "./pages/StockPage";
import SupplierReturnPage from "./pages/SupplierReturnPage";
import SupplierReturnsPage from "./pages/SupplierReturnsPage";
import SupplierInvoicePage from "./pages/SupplierInvoicePage";
import SupplierInvoicesPage from "./pages/SupplierInvoicesPage";
import PurchaseOrderPage from "./pages/PurchaseOrderPage";
import PurchasingReportsPage from "./pages/PurchasingReportsPage";
import PurchaseOrdersPage from "./pages/PurchaseOrdersPage";
import PurchaseRequestPage from "./pages/PurchaseRequestPage";
import ChequesPage from "./pages/ChequesPage";
import BankStatementsPage from "./pages/BankStatementsPage";
import ReconciliationPage from "./pages/ReconciliationPage";
import PettyCashPage from "./pages/PettyCashPage";
import StockWorkPage from "./pages/StockWorkPage";
import FixedAssetsPage from "./pages/FixedAssetsPage";
import TaxReportsPage from "./pages/TaxReportsPage";
import RevaluationPage from "./pages/RevaluationPage";
import BudgetsPage from "./pages/BudgetsPage";
import BudgetPage from "./pages/BudgetPage";
import ClosePage from "./pages/ClosePage";
import PurchaseRequestsPage from "./pages/PurchaseRequestsPage";
import ReorderPage from "./pages/ReorderPage";
import StoresPage from "./pages/settings/StoresPage";
import SalesOrdersPage from "./pages/SalesOrdersPage";
import PayPage from "./pages/PayPage";
import JournalPage from "./pages/JournalPage";
import ManualJournalPage from "./pages/ManualJournalPage";
import OpeningStockPage from "./pages/OpeningStockPage";
import OpeningStocksPage from "./pages/OpeningStocksPage";
import ManualJournalsPage from "./pages/ManualJournalsPage";
import RecurringJournalPage from "./pages/RecurringJournalPage";
import RecurringJournalsPage from "./pages/RecurringJournalsPage";
import PeriodsPage from "./pages/PeriodsPage";
import ReviewPage from "./pages/ReviewPage";
import SalesAccountsPage from "./pages/SalesAccountsPage";
import TaxInvoicePage from "./pages/TaxInvoicePage";
import TaxInvoicesPage from "./pages/TaxInvoicesPage";
import TaxesPage from "./pages/TaxesPage";
import VoucherPage from "./pages/VoucherPage";
import VouchersPage from "./pages/VouchersPage";
import NotificationSettingsPage from "./pages/NotificationSettingsPage";
import PayeesPage from "./pages/PayeesPage";
import QuotationCostingPage from "./pages/QuotationCostingPage";
import QuotationPage from "./pages/QuotationPage";
import QuotationsPage from "./pages/QuotationsPage";
import TwoFactorSetupPage from "./pages/TwoFactorSetupPage";
import AccessReviewPage from "./pages/admin/AccessReviewPage";
import AuditLogPage from "./pages/admin/AuditLogPage";
import UserAccessPage from "./pages/admin/UserAccessPage";
import UsersPage from "./pages/admin/UsersPage";
import CompanyPage from "./pages/settings/CompanyPage";
import DivisionsPage from "./pages/settings/DivisionsPage";
import FactoryPage from "./pages/settings/FactoryPage";
import NumberSeriesPage from "./pages/settings/NumberSeriesPage";
import ShiftsPage from "./pages/settings/ShiftsPage";
import CurrenciesPage from "./pages/settings/CurrenciesPage";
import QuotationLimitsPage from "./pages/settings/QuotationLimitsPage";
import TaxRatesPage from "./pages/settings/TaxRatesPage";
import ApprovalMatrixPage from "./pages/settings/ApprovalMatrixPage";
import DocumentEmailPage from "./pages/settings/DocumentEmailPage";
import VoucherTypesPage from "./pages/settings/VoucherTypesPage";
import SentEmailsPage from "./pages/admin/SentEmailsPage";

/** Hands the signed-in user (from the layout) to a page. */
function WithMe({ page }: { page: (me: CurrentUser) => ReactNode }) {
  return <>{page(useMe())}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/account/two-factor"
        element={<AuthGate allowPending>{() => <TwoFactorSetupPage />}</AuthGate>}
      />
      <Route
        path="/account/password"
        element={
          <AuthGate allowPending>
            {(user) =>
              user.requirements.includes("password_change_required") ? (
                <ChangePasswordPage firstTime />
              ) : (
                <AppLayout user={user} />
              )
            }
          </AuthGate>
        }
      >
        <Route index element={<ChangePasswordPage />} />
      </Route>

      {/* Every signed-in page sits inside the layout: side menu, top bar, user menu. */}
      <Route element={<AuthGate>{(user) => <AppLayout user={user} />}</AuthGate>}>
        <Route index element={<WithMe page={(me) => <HomePage user={me} />} />} />
        <Route path="account/notifications" element={<NotificationSettingsPage />} />
        <Route
          path="bank-accounts"
          element={<WithMe page={(me) => <BankAccountsPage me={me} />} />}
        />
        <Route path="payees" element={<WithMe page={(me) => <PayeesPage me={me} />} />} />
        <Route path="customers" element={<WithMe page={(me) => <CustomersPage me={me} />} />} />
        <Route path="quotations" element={<WithMe page={(me) => <QuotationsPage me={me} />} />} />
        <Route path="quotations/new" element={<QuotationPage />} />
        <Route path="quotations/:id" element={<QuotationPage />} />
        <Route path="quotations/:id/costing" element={<QuotationCostingPage />} />
        <Route path="proformas" element={<ProformasPage />} />
        <Route path="proformas/:id" element={<ProformaPage />} />
        <Route path="sales-orders" element={<WithMe page={(me) => <SalesOrdersPage me={me} />} />} />
        <Route path="sales-orders/:id" element={<SalesOrderPage />} />
        <Route path="credit-notes" element={<CreditNotesPage />} />
        <Route path="credit-notes/:id" element={<CreditNotePage />} />
        <Route path="tax-invoices" element={<TaxInvoicesPage />} />
        <Route path="tax-invoices/:id" element={<TaxInvoicePage />} />
        <Route path="sales-accounts" element={<WithMe page={(me) => <SalesAccountsPage me={me} />} />} />
        <Route path="delivery-notes" element={<DeliveryNotesPage />} />
        <Route path="delivery-notes/:id" element={<DeliveryNotePage />} />
        <Route path="sales/reports" element={<SalesReportsPage />} />
        <Route path="items" element={<ItemsPage />} />
        <Route path="purchase-orders" element={<WithMe page={(me) => <PurchaseOrdersPage me={me} />} />} />
        <Route path="purchase-orders/:id" element={<PurchaseOrderPage />} />
        <Route path="purchase-requests" element={<PurchaseRequestsPage />} />
        <Route path="purchase-requests/:id" element={<PurchaseRequestPage />} />
        <Route path="reorder" element={<ReorderPage />} />
        <Route path="cheques" element={<ChequesPage />} />
        <Route path="bank-statements" element={<BankStatementsPage />} />
        <Route path="reconciliation" element={<ReconciliationPage />} />
        <Route path="petty-cash" element={<PettyCashPage />} />
        <Route path="stores-work" element={<StockWorkPage />} />
        <Route path="fixed-assets" element={<FixedAssetsPage />} />
        <Route path="tax-reports" element={<TaxReportsPage />} />
        <Route path="revaluation" element={<RevaluationPage />} />
        <Route path="budgets" element={<BudgetsPage />} />
        <Route path="budgets/:id" element={<BudgetPage />} />
        <Route path="month-end" element={<ClosePage />} />
        <Route path="goods-receipts" element={<WithMe page={(me) => <GoodsReceiptsPage me={me} />} />} />
        <Route path="goods-receipts/:id" element={<GoodsReceiptPage />} />
        <Route path="inspections" element={<InspectionsPage />} />
        <Route path="inspections/:id" element={<InspectionPage />} />
        <Route path="inspection-plans" element={<InspectionPlansPage />} />
        <Route path="stock" element={<StockPage />} />
        <Route path="purchasing/reports" element={<PurchasingReportsPage />} />
        <Route path="supplier-returns" element={<WithMe page={(me) => <SupplierReturnsPage me={me} />} />} />
        <Route path="supplier-returns/:id" element={<SupplierReturnPage />} />
        <Route path="supplier-invoices" element={<WithMe page={(me) => <SupplierInvoicesPage me={me} />} />} />
        <Route path="supplier-invoices/:id" element={<SupplierInvoicePage />} />
        <Route path="settings/stores" element={<WithMe page={(me) => <StoresPage me={me} />} />} />
        <Route path="costing-rates" element={<WithMe page={(me) => <CostingRatesPage me={me} />} />} />
        <Route
          path="chart-of-accounts"
          element={<WithMe page={(me) => <ChartOfAccountsPage me={me} />} />}
        />
        <Route path="journal" element={<WithMe page={(me) => <JournalPage me={me} />} />} />
        <Route path="journals/manual" element={<WithMe page={(me) => <ManualJournalsPage me={me} />} />} />
        <Route path="journals/manual/:id" element={<ManualJournalPage />} />
        <Route path="journals/recurring" element={<WithMe page={(me) => <RecurringJournalsPage me={me} />} />} />
        <Route path="journals/recurring/:id" element={<RecurringJournalPage />} />
        <Route path="reports/financial" element={<FinancialReportsPage />} />
        <Route path="opening-stock" element={<WithMe page={(me) => <OpeningStocksPage me={me} />} />} />
        <Route path="opening-stock/:id" element={<OpeningStockPage />} />
        <Route path="taxes" element={<WithMe page={(me) => <TaxesPage me={me} />} />} />
        <Route path="vouchers" element={<WithMe page={(me) => <VouchersPage me={me} />} />} />
        <Route path="vouchers/review" element={<ReviewPage />} />
        <Route path="vouchers/approve" element={<DirectorPage />} />
        <Route path="vouchers/deleted" element={<DeletedVouchersPage />} />
        <Route path="vouchers/amendments" element={<AmendmentsPage />} />
        <Route path="vouchers/cancellations" element={<CancellationsPage />} />
        <Route path="vouchers/reports" element={<VoucherReportsPage />} />
        <Route path="payments" element={<WithMe page={(me) => <PaymentsPage me={me} />} />} />
        <Route path="payments/new" element={<PayPage />} />
        <Route path="advances" element={<WithMe page={(me) => <AdvancesPage me={me} />} />} />
        <Route path="advances/:id" element={<AdvancePage />} />
        <Route path="receipts" element={<WithMe page={(me) => <ReceiptsPage me={me} />} />} />
        <Route path="receipts/:id" element={<ReceiptPage />} />
        <Route path="receivables" element={<ReceivablesPage />} />
        <Route path="receivables/:id" element={<StatementPage />} />
        <Route path="credit-holds" element={<CreditHoldsPage />} />
        <Route path="payables" element={<PayablesPage />} />
        <Route path="supplier-statements" element={<WithMe page={(me) => <SupplierStatementsPage me={me} />} />} />
        <Route path="supplier-statements/:id" element={<SupplierStatementPage />} />
        <Route path="vouchers/:id" element={<WithMe page={(me) => <VoucherPage me={me} />} />} />
        <Route
          path="accounting-periods"
          element={<WithMe page={(me) => <PeriodsPage me={me} />} />}
        />
        <Route path="admin/users" element={<WithMe page={(me) => <UsersPage me={me} />} />} />
        <Route
          path="admin/users/:id"
          element={<WithMe page={(me) => <UserAccessPage me={me} />} />}
        />
        <Route
          path="admin/access-review"
          element={<WithMe page={(me) => <AccessReviewPage me={me} />} />}
        />
        <Route path="admin/audit" element={<AuditLogPage />} />
        <Route
          path="settings/company"
          element={<WithMe page={(me) => <CompanyPage me={me} />} />}
        />
        <Route
          path="settings/divisions"
          element={<WithMe page={(me) => <DivisionsPage me={me} />} />}
        />
        <Route
          path="settings/factory"
          element={<WithMe page={(me) => <FactoryPage me={me} />} />}
        />
        <Route
          path="settings/shifts"
          element={<WithMe page={(me) => <ShiftsPage me={me} />} />}
        />
        <Route
          path="settings/currencies"
          element={<WithMe page={(me) => <CurrenciesPage me={me} />} />}
        />
        <Route
          path="settings/quotation-limits"
          element={<WithMe page={(me) => <QuotationLimitsPage me={me} />} />}
        />
        <Route path="settings/tax-rates" element={<TaxRatesPage />} />
        <Route
          path="settings/number-series"
          element={<WithMe page={(me) => <NumberSeriesPage me={me} />} />}
        />
        <Route
          path="settings/approval-matrix"
          element={<WithMe page={(me) => <ApprovalMatrixPage me={me} />} />}
        />
        <Route
          path="settings/document-email"
          element={<WithMe page={(me) => <DocumentEmailPage me={me} />} />}
        />
        <Route path="admin/sent-emails" element={<SentEmailsPage />} />
        <Route
          path="settings/voucher-types"
          element={<WithMe page={(me) => <VoucherTypesPage me={me} />} />}
        />
      </Route>
    </Routes>
  );
}
