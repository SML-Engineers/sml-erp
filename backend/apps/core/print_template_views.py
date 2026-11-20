"""The template designer's API (owner, 13 Nov 2026). Rules live in print_templates.py: the
Admin and the Director save, reset, bring back and preview; anyone with Settings view sees
the layouts and their history."""

from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import print_templates
from .permissions import AreaAccess
from .print_templates import TemplateError


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class _Templates(APIView):
    permission_classes = [AreaAccess]
    access_area = "settings"
    access_write_level = "view"  # the service checks "edit_print_templates"


class PrintTemplateListView(_Templates):
    def get(self, request):
        return Response(
            {
                "documents": print_templates.documents(),
                "can_edit": print_templates.can_edit(request.user),
            }
        )


class PrintTemplateView(_Templates):
    def get(self, request, document):
        try:
            return Response(print_templates.page(request.user, document))
        except TemplateError as error:
            return _error(error)

    def post(self, request, document):
        """Save the layout as a new version, reset it, or bring back an old version."""
        data = request.data
        try:
            if data.get("reset"):
                print_templates.reset(request.user, document)
            elif data.get("restore"):
                print_templates.restore(request.user, document, data.get("restore"))
            else:
                print_templates.save(request.user, document, data.get("layout"), data.get("note"))
            return Response(print_templates.page(request.user, document))
        except TemplateError as error:
            return _error(error)


class PrintTemplatePreviewView(_Templates):
    def post(self, request, document):
        try:
            pdf = print_templates.preview(request.user, document, request.data.get("layout"))
        except TemplateError as error:
            return _error(error)
        answer = HttpResponse(pdf, content_type="application/pdf")
        answer["Content-Disposition"] = f'inline; filename="{document}-preview.pdf"'
        return answer
