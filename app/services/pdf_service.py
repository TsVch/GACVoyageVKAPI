from pathlib import Path
from app.config import get_settings
from app.contracts.consent_template import generate_consent_pdf
from app.contracts.contract_template import generate_contract_pdf
from app.models.booking import Booking
class PDFService:
    def __init__(self) -> None:
        self.settings = get_settings(); self.output = Path(self.settings.file_storage_path); self.output.mkdir(parents=True, exist_ok=True)
    def generate_booking_documents(self, booking: Booking) -> dict[str, str]:
        order = {"booking_id": booking.id, "name": booking.name, "phone": booking.phone, "price": float(booking.tour.price), "date": booking.date.isoformat()}
        return {"contract": generate_contract_pdf(order, self.output, signed=True), "consent": generate_consent_pdf(booking.name, booking.phone, self.output, preview=False)}
