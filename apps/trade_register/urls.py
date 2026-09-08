from django.urls import path

from . import views as v

urlpatterns = [
    path("entries/",            v.TradeRegisterEntryListCreateView.as_view()),
    path("entries/<int:pk>/",   v.TradeRegisterEntryDetailView.as_view()),
    # Expiry diary — what has run out and what is about to.
    path("diary/",              v.TradeDiaryView.as_view()),
    path("categories/",         v.TradeProductCategoryListView.as_view()),
    path("actions/",            v.TradeActionListView.as_view()),
    path("products/",           v.TradeProductListView.as_view()),
    path("products/manage/",    v.TradeProductAdminListView.as_view()),
    path("products/<int:pk>/",  v.TradeProductAdminDetailView.as_view()),
    # The tariff book products are charged under.
    path("tariffs/",            v.TradeTariffListView.as_view()),
    path("tariffs/<int:pk>/",   v.TradeTariffDetailView.as_view()),
    path("branches/",           v.BranchListView.as_view()),
    path("rm-lookup/",          v.RMLookupView.as_view()),
    path("customer-lookup/",    v.CustomerLookupView.as_view()),
    path("currencies/",         v.TradeCurrencyListView.as_view()),
    path("product-lookup/",     v.ProductLookupView.as_view()),
    path("reference-preview/",  v.ReferencePreviewView.as_view()),
]
