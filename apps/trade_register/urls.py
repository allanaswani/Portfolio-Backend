from django.urls import path

from . import views as v

urlpatterns = [
    path("entries/",            v.TradeRegisterEntryListCreateView.as_view()),
    path("entries/<int:pk>/",   v.TradeRegisterEntryDetailView.as_view()),
    path("products/",           v.TradeProductListView.as_view()),
    path("rm-lookup/",          v.RMLookupView.as_view()),
    path("reference-preview/",  v.ReferencePreviewView.as_view()),
]
