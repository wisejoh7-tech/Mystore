from abc import ABC, abstractmethod
import hmac
import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class TransferNotAuthorizedError(PermissionError):
    """
    Exception thrown when a transfer or payment initiation attempt is made without explicit authorization & testing.
    """
    pass


class BaseBankProviderAdapter(ABC):
    """
    Abstract base class for external banking provider adapters (Plaid, Mono, Sandbox Mock, etc.)
    """

    transfers_enabled_by_default: bool = False

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @abstractmethod
    def create_link_token(self, user_id: str, redirect_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates a temporary link token or OAuth URL for initiating account connection in the frontend.
        """
        pass

    @abstractmethod
    def exchange_public_token(self, public_token: str) -> Dict[str, Any]:
        """
        Exchanges public token / auth code received after user authorizes in provider widget.
        Must return dict containing access_token, external_connection_id, and provider confirmation timestamp.
        """
        pass

    @abstractmethod
    def fetch_accounts(self, access_token: str) -> List[Dict[str, Any]]:
        """
        Fetches authorized bank accounts linked to the connection.
        """
        pass

    @abstractmethod
    def fetch_transactions(
        self,
        access_token: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetches transactions from the bank provider within specified date range.
        Each item must include 'external_transaction_id', 'amount', 'date', 'description', 'account_id', etc.
        """
        pass

    @abstractmethod
    def verify_webhook_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        """
        Verifies provider webhook signature.
        """
        pass

    def initiate_transfer(
        self,
        access_token: str,
        source_account_id: str,
        destination_account_number: str,
        amount: float,
        currency: str = "NGN",
        is_explicitly_authorized: bool = False
    ) -> Dict[str, Any]:
        """
        Initiates money transfer. Enforces safety guardrail: transfers remain disabled unless explicitly authorized.
        """
        if not is_explicitly_authorized or not self.transfers_enabled_by_default:
            logger.warning(f"Blocked transfer attempt on provider {self.provider_name} for amount {amount} {currency}")
            raise TransferNotAuthorizedError(
                "Transfers and payment initiation are currently disabled by default. "
                "They require explicit authorization and full verification before execution."
            )
        return self._execute_transfer(access_token, source_account_id, destination_account_number, amount, currency)

    def _execute_transfer(
        self,
        access_token: str,
        source_account_id: str,
        destination_account_number: str,
        amount: float,
        currency: str
    ) -> Dict[str, Any]:
        """
        Override in subclasses if provider supports transfers after explicit authorization.
        """
        raise NotImplementedError("Transfer execution is not supported by this provider adapter.")


class MockBankProviderAdapter(BaseBankProviderAdapter):
    """
    Mock Provider Adapter for testing and sandbox environments.
    Strictly enforces authorization confirmation and credential safety.
    """

    provider_name = "mock"
    transfers_enabled_by_default = False

    def create_link_token(self, user_id: str, redirect_url: Optional[str] = None) -> Dict[str, Any]:
        return {
            "link_token": f"mock_link_token_{user_id}",
            "expiration": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "connect_url": f"https://mock-bank.example.com/connect?token=mock_link_token_{user_id}"
        }

    def exchange_public_token(self, public_token: str) -> Dict[str, Any]:
        if not public_token or not public_token.startswith("mock_pub_"):
            raise ValueError("Invalid public token provided by mock bank provider.")

        now = datetime.now(timezone.utc)
        return {
            "access_token": f"mock_access_token_{public_token.replace('mock_pub_', '')}",
            "external_connection_id": f"mock_conn_{public_token.replace('mock_pub_', '')}",
            "provider_confirmed_at": now.isoformat(),
            "institution_name": "First Bank Mock",
            "status": "CONNECTED"
        }

    def fetch_accounts(self, access_token: str) -> List[Dict[str, Any]]:
        if not access_token:
            raise ValueError("Access token required to fetch accounts.")

        return [
            {
                "external_account_id": "mock_acc_001",
                "bank_name": "First Bank Mock",
                "account_name": "Mock Operating Account",
                "account_number_mask": "****5678",
                "account_type": "CHECKING",
                "currency": "NGN",
                "ledger_balance": 1500000.00,
                "available_balance": 1450000.00,
            },
            {
                "external_account_id": "mock_acc_002",
                "bank_name": "First Bank Mock",
                "account_name": "Mock Reserve Savings",
                "account_number_mask": "****9012",
                "account_type": "SAVINGS",
                "currency": "NGN",
                "ledger_balance": 500000.00,
                "available_balance": 500000.00,
            }
        ]

    def fetch_transactions(
        self,
        access_token: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        return [
            {
                "external_transaction_id": "mock_tx_1001",
                "external_account_id": "mock_acc_001",
                "amount": 25000.00,
                "currency": "NGN",
                "date": (now - timedelta(days=1)).isoformat(),
                "description": "Customer Payment Order #101",
                "category": "INCOME",
                "is_charge": False
            },
            {
                "external_transaction_id": "mock_tx_1002",
                "external_account_id": "mock_acc_001",
                "amount": -525.00,
                "currency": "NGN",
                "date": (now - timedelta(days=1)).isoformat(),
                "description": "Monthly Account Maintenance Fee",
                "category": "BANK_FEE",
                "is_charge": True
            },
            {
                "external_transaction_id": "mock_tx_1003",
                "external_account_id": "mock_acc_001",
                "amount": -15000.00,
                "currency": "NGN",
                "date": (now - timedelta(days=2)).isoformat(),
                "description": "Utility Bill Expense Payment",
                "category": "EXPENSE",
                "is_charge": False
            }
        ]

    def verify_webhook_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        if not signature_header:
            return False
        # Expected signature for test mock: sha256 HMAC using key 'mock_webhook_secret'
        expected = hmac.new(b"mock_webhook_secret", payload_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_header)


class MonoProviderAdapter(BaseBankProviderAdapter):
    provider_name = "mono"
    transfers_enabled_by_default = False

    def create_link_token(self, user_id: str, redirect_url: Optional[str] = None) -> Dict[str, Any]:
        return {
            "link_token": f"mono_connect_key_{user_id}",
            "provider": "mono"
        }

    def exchange_public_token(self, public_token: str) -> Dict[str, Any]:
        return {
            "access_token": f"mono_sec_token_{public_token}",
            "external_connection_id": f"mono_account_id_{public_token}",
            "provider_confirmed_at": datetime.now(timezone.utc).isoformat(),
            "institution_name": "Mono Linked Bank",
            "status": "CONNECTED"
        }

    def fetch_accounts(self, access_token: str) -> List[Dict[str, Any]]:
        return []

    def fetch_transactions(
        self,
        access_token: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        return []

    def verify_webhook_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        return True


class BankProviderRegistry:
    """
    Registry for obtaining banking provider adapters.
    """
    _adapters: Dict[str, BaseBankProviderAdapter] = {
        "mock": MockBankProviderAdapter(),
        "mono": MonoProviderAdapter(),
    }

    @classmethod
    def get_adapter(cls, provider_name: str) -> BaseBankProviderAdapter:
        adapter = cls._adapters.get(provider_name.lower())
        if not adapter:
            raise ValueError(f"Unsupported banking provider: {provider_name}")
        return adapter

    @classmethod
    def register_adapter(cls, provider_name: str, adapter: BaseBankProviderAdapter):
        cls._adapters[provider_name.lower()] = adapter
