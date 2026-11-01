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
import AdvancesPage from "./pages/AdvancesPage";
import PaymentsPage from "./pages/PaymentsPage";
import ProformaPage from "./pages/ProformaPage";
import ProformasPage from "./pages/ProformasPage";
import SalesOrderPage from "./pages/SalesOrderPage";
import SalesReportsPage from "./pages/SalesReportsPage";
import GoodsReceiptPage from "./pages/GoodsReceiptPage";
import GoodsReceiptsPage from "./pages/GoodsReceiptsPage";
import InspectionPage from "./pages/InspectionPage";
import InspectionPlansPage from "./pages/InspectionPlansPage";
import InspectionsPage from "./pages/InspectionsPage";
import ItemsPage from "./pages/ItemsPage";
import PurchaseOrderPage from "./pages/PurchaseOrderPage";
import PurchaseOrdersPage from "./pages/PurchaseOrdersPage";
import StoresPage from "./pages/settings/StoresPage";
import SalesOrdersPage from "./pages/SalesOrdersPage";
import PayPage from "./pages/PayPage";
import JournalPage from "./pages/JournalPage";
import PeriodsPage from "./pages/PeriodsPage";
import ReviewPage from "./pages/ReviewPage";
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
        <Route path="sales/reports" element={<SalesReportsPage />} />
        <Route path="items" element={<ItemsPage />} />
        <Route path="purchase-orders" element={<WithMe page={(me) => <PurchaseOrdersPage me={me} />} />} />
        <Route path="purchase-orders/:id" element={<PurchaseOrderPage />} />
        <Route path="goods-receipts" element={<WithMe page={(me) => <GoodsReceiptsPage me={me} />} />} />
        <Route path="goods-receipts/:id" element={<GoodsReceiptPage />} />
        <Route path="inspections" element={<InspectionsPage />} />
        <Route path="inspections/:id" element={<InspectionPage />} />
        <Route path="inspection-plans" element={<InspectionPlansPage />} />
        <Route path="settings/stores" element={<WithMe page={(me) => <StoresPage me={me} />} />} />
        <Route path="costing-rates" element={<WithMe page={(me) => <CostingRatesPage me={me} />} />} />
        <Route
          path="chart-of-accounts"
          element={<WithMe page={(me) => <ChartOfAccountsPage me={me} />} />}
        />
        <Route path="journal" element={<WithMe page={(me) => <JournalPage me={me} />} />} />
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
