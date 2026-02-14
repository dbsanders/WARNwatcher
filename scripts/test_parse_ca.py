import io
import sys
from pathlib import Path

from openpyxl import Workbook

# Minimal local test helper:
# - If a path is provided, parse that XLSX.
# - Otherwise, generate an in-memory sample and parse it.
sys.path.append(str(Path(__file__).resolve().parents[1] / "lambda" / "ingest"))
import app  # noqa: E402


def build_sample_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Employer", "City", "County", "Number of Employees", "Notice Date", "Layoff Date"])
    ws.append(["Acme Logistics", "Los Angeles", "Los Angeles", 120, "01/14/2026", "02/15/2026"])
    ws.append(["Northwind Foods", "Fresno", "Fresno", 35, "01/10/2026", "03/01/2026"])
    buff = io.BytesIO()
    wb.save(buff)
    return buff.getvalue()


def main() -> None:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        content = path.read_bytes()
    else:
        content = build_sample_xlsx()

    notices = app.parse_ca_xlsx(content)
    print(f"Parsed notices: {len(notices)}")
    for n in notices:
        print(n)


if __name__ == "__main__":
    main()
