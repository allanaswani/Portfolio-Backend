import csv
import io
from typing import Any

from django.http import HttpResponse


def build_csv_response(filename: str, headers: list[str], rows: list[list[Any]]) -> HttpResponse:
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(headers)
    writer.writerows(rows)
    return response


def parse_csv_upload(file_obj) -> list[dict]:
    decoded = file_obj.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(decoded))
    return list(reader)
