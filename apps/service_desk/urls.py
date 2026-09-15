from django.urls import path

from . import views as v

urlpatterns = [
    # The queue and one ticket. Addressed by reference, not id — a reference is
    # what appears in the emails people will paste back at you.
    path("tickets/", v.TicketListCreateView.as_view()),
    path("tickets/<str:reference>/", v.TicketDetailView.as_view()),

    # Every state change is its own endpoint. There is no PATCH that can set a
    # status, because each of these records a step and tells somebody.
    path("tickets/<str:reference>/comment/", v.TicketCommentView.as_view()),
    path("tickets/<str:reference>/status/",  v.TicketStatusView.as_view()),
    path("tickets/<str:reference>/assign/",  v.TicketAssignView.as_view()),
    path("tickets/<str:reference>/resolve/", v.TicketResolveView.as_view()),
    path("tickets/<str:reference>/confirm/", v.TicketConfirmView.as_view()),
    path("tickets/<str:reference>/reopen/",  v.TicketReopenView.as_view()),
    path("tickets/<str:reference>/cancel/",  v.TicketCancelView.as_view()),

    # Reference data.
    path("categories/",           v.CategoryListCreateView.as_view()),
    path("categories/<int:pk>/",  v.CategoryDetailView.as_view()),
    # Addresses notified without an account — several of the desk have no login.
    path("recipients/",           v.DeskRecipientListCreateView.as_view()),
    path("recipients/<int:pk>/",  v.DeskRecipientDetailView.as_view()),
    path("holidays/",             v.HolidayListCreateView.as_view()),
    path("holidays/<int:pk>/",    v.HolidayDetailView.as_view()),
    path("settings/",             v.DeskSettingsView.as_view()),
    path("handlers/",             v.HandlerListView.as_view()),
    # Who is on the desk, and finding people to put on it.
    path("team/",                 v.TeamView.as_view()),
    path("team/search/",          v.StaffSearchView.as_view()),

    # Counts for the sidebar, and the reporting the desk is measured by.
    path("my-desk/", v.MyDeskView.as_view()),
    path("reports/", v.ReportsView.as_view()),
]
