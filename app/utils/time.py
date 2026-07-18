from datetime import datetime, timezone


def utcnow() -> datetime:
    """Agora em UTC (timezone-aware). Todo datetime persistido usa UTC;
    conversão para America/Sao_Paulo acontece na camada de domínio/exibição."""
    return datetime.now(timezone.utc)
