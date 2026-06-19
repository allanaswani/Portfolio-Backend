from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema
from django.utils import timezone

from .models import Slide
from .serializers import SlideSerializer


@extend_schema(tags=["Slideshow"])
class SlideListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SlideSerializer

    def get_queryset(self):
        now = timezone.now()
        return Slide.objects.filter(
            is_active=True
        ).exclude(
            expires_at__lt=now
        )


@extend_schema(tags=["Slideshow"])
class SlideDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SlideSerializer
    queryset = Slide.objects.all()


@extend_schema(tags=["Slideshow"])
class TriggerSlideRefreshView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from tasks.slideshow_tasks import precompute_all_slides
        try:
            precompute_all_slides.delay()
            return Response({"detail": "Slide refresh triggered."})
        except Exception:
            # Celery broker unavailable — run synchronously
            count = precompute_all_slides()
            return Response({"detail": f"Slides refreshed synchronously ({count} slides)."})
