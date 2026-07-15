from django.urls import path
from . import views as v

urlpatterns = [
    path("files/",                v.FileListCreateView.as_view()),
    path("files/<int:pk>/",       v.FileDetailView.as_view()),
    path("files/<int:pk>/issue/", v.IssueView.as_view()),
    path("files/<int:pk>/return/", v.ReturnView.as_view()),
    path("cards/",                v.CardListView.as_view()),
    path("overdue/",              v.OverdueReportView.as_view()),
    path("users/",                v.UserLookupView.as_view()),
    path("my-files/",             v.MyFilesView.as_view()),

    # Phase 2 — archives (§3.5) & destruction (§3.6)
    path("consignments/",              v.ConsignmentListCreateView.as_view()),
    path("consignments/<int:pk>/",     v.ConsignmentDetailView.as_view()),
    path("consignments/<int:pk>/receive/", v.ReceiveConsignmentView.as_view()),
    path("boxes/",                     v.BoxListView.as_view()),
    path("retention-due/",             v.RetentionDueView.as_view()),
    path("destructions/",              v.DestructionListCreateView.as_view()),
    path("destructions/<int:pk>/",     v.DestructionDetailView.as_view()),
    path("destructions/<int:pk>/approve/", v.ApproveDestructionView.as_view()),
    path("destructions/<int:pk>/destroy/", v.DestroyBatchView.as_view()),
    path("destructions/<int:pk>/certify/", v.CertifyDestructionView.as_view()),
]
