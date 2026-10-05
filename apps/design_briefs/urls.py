from django.urls import path

from . import views as v

urlpatterns = [
    # The board the office screen polls. First, because it is the most-hit
    # route and the one with no id in it.
    path("board/", v.BoardView.as_view()),
    path("my-pipeline/", v.MyPipelineView.as_view()),
    path("summary/", v.SummaryView.as_view()),

    # Reference data for the forms.
    path("calendar/", v.CalendarView.as_view()),

    path("meta/", v.MetaView.as_view()),
    path("designers/", v.DesignerListView.as_view()),
    path("departments/", v.DepartmentListView.as_view()),

    # The queue and one brief. Addressed by reference, not id — a reference is
    # what people paste at each other.
    path("briefs/", v.BriefListCreateView.as_view()),
    path("briefs/<str:reference>/", v.BriefDetailView.as_view()),
    path("briefs/<str:reference>/timeline/", v.BriefTimelineView.as_view()),

    # Every state change is its own endpoint. There is no PATCH that can set a
    # status, because each of these records a step with an actor against it.
    path("briefs/<str:reference>/assign/",  v.BriefAssignView.as_view()),
    path("briefs/<str:reference>/start/",   v.BriefStartView.as_view()),
    path("briefs/<str:reference>/submit/",  v.BriefSubmitView.as_view()),
    path("briefs/<str:reference>/rework/",  v.BriefReworkView.as_view()),
    path("briefs/<str:reference>/approve/", v.BriefApproveView.as_view()),
    path("briefs/<str:reference>/cancel/",  v.BriefCancelView.as_view()),
    path("briefs/<str:reference>/reopen/",  v.BriefReopenView.as_view()),
    path("briefs/<str:reference>/note/",    v.BriefNoteView.as_view()),

    # The artwork. A proof's image is served from its own route so the browser
    # caches it and a board listing stays a few kilobytes.
    path("briefs/<str:reference>/proofs/", v.BriefProofView.as_view()),
    path("proofs/<int:pk>/thumb/",   v.ProofThumbView.as_view()),
    path("proofs/<int:pk>/preview/", v.ProofPreviewView.as_view()),

    # The conversation, and the checklist of what the brief has to produce.
    path("briefs/<str:reference>/comments/", v.BriefCommentView.as_view()),
    path("briefs/<str:reference>/deliverables/", v.BriefDeliverableView.as_view()),
    path("briefs/<str:reference>/deliverables/<int:pk>/tick/",
         v.DeliverableTickView.as_view()),
]
