from pathlib import Path
import uuid

from app.config import get_settings
from app.contracts.consent_template import generate_consent_pdf
from app.contracts.contract_template import generate_contract_pdf
from app.models.booking import Booking


class PDFService:
    def __init__(self) -> None:
        self.settings = get_settings()

        # Директория хранения PDF
        self.output = Path(self.settings.file_storage_path)

        # Создаем директорию если ее нет
        self.output.mkdir(parents=True, exist_ok=True)

    def _build_public_url(self, filename: str) -> str:
        """
        Формирует публичную ссылку на файл через Railway/FastAPI
        """
        base = self.settings.app_base_url.rstrip("/")
        return f"{base}/files/{filename}"

    def generate_booking_documents(self, booking: Booking) -> dict[str, str]:
        """
        Генерирует PDF документы и возвращает публичные ссылки
        """

        unique_id = uuid.uuid4().hex[:10]

        contract_filename = f"contract_{booking.id}_{unique_id}.pdf"
        consent_filename = f"consent_{booking.id}_{unique_id}.pdf"

        order = {
            "booking_id": booking.id,
            "name": booking.name,
            "phone": booking.phone,
            "price": float(booking.tour.price),
            "date": booking.date.isoformat(),
        }

        # Генерация PDF
        contract_path = generate_contract_pdf(
            order,
            self.output,
            filename=contract_filename,
            signed=True,
        )

        consent_path = generate_consent_pdf(
            booking.name,
            booking.phone,
            self.output,
            filename=consent_filename,
            preview=False,
        )

        # На случай если templates возвращают Path
        contract_name = Path(contract_path).name
        consent_name = Path(consent_path).name

        return {
            "contract_path": str(contract_path),
            "consent_path": str(consent_path),
            "contract_url": self._build_public_url(contract_name),
            "consent_url": self._build_public_url(consent_name),
        }