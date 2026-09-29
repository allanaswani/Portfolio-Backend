from django.urls import path

from . import views as v

urlpatterns = [
    path("entries/",            v.PipelineListCreateView.as_view()),
    path("entries/<int:pk>/",   v.PipelineDetailView.as_view()),
    # What a Team Leader opens this for.
    path("summary/",            v.PipelineSummaryView.as_view()),
    path("export/",             v.PipelineExportView.as_view()),
    # Choices and product suggestions, so the form never hard-codes them.
    path("options/",            v.PipelineOptionsView.as_view()),
    # Loading the workbook without needing a shell on the host.
    path("upload/",             v.PipelineUploadView.as_view()),
]
