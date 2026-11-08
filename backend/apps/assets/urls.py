from django.urls import path

from . import views as v

urlpatterns = [
    path("asset-classes/", v.ClassListView.as_view(), name="asset-classes"),
    path("asset-classes/<int:pk>/rates/", v.ClassRateView.as_view(), name="asset-class-rates"),
    path(
        "asset-classes/rates/<int:pk>/decide/",
        v.RateDecideView.as_view(),
        name="asset-class-rate-decide",
    ),
    path("fixed-assets/", v.AssetListView.as_view(), name="fixed-assets"),
    path("fixed-assets/waiting/", v.WaitingView.as_view(), name="fixed-assets-waiting"),
    path("fixed-assets/send-all/", v.SendAllView.as_view(), name="fixed-assets-send-all"),
    path(
        "fixed-assets/terms/<int:pk>/decide/",
        v.TermsDecideView.as_view(),
        name="fixed-asset-terms-decide",
    ),
    path("fixed-assets/<int:pk>/terms/", v.TermsView.as_view(), name="fixed-asset-terms"),
    path("fixed-assets/<int:pk>/", v.AssetDetailView.as_view(), name="fixed-asset"),
    path("fixed-assets/<int:pk>/dispose/", v.DisposeView.as_view(), name="fixed-asset-dispose"),
    path("depreciation/", v.RunListView.as_view(), name="depreciation-runs"),
    path(
        "depreciation/<int:pk>/post/",
        v.RunActionView.as_view(action="post"),
        name="depreciation-post",
    ),
    path(
        "depreciation/<int:pk>/discard/",
        v.RunActionView.as_view(action="discard"),
        name="depreciation-discard",
    ),
]
