class BudgetExceeded(Exception):
    pass


class Budget:
    """Per-run spend cap. A call is refused up front if its catalog price would cross the cap."""

    def __init__(self, max_spend_usd: float):
        self.max_micro = int(round(max_spend_usd * 1_000_000))
        self.spent_micro = 0

    def check(self, est_micro: int) -> None:
        if self.spent_micro + est_micro > self.max_micro:
            raise BudgetExceeded(
                f"next call (~${est_micro / 1e6:.4f}) would exceed --max-spend "
                f"${self.max_micro / 1e6:.2f} (spent ${self.spent_micro / 1e6:.4f})"
            )

    def spend(self, micro: int) -> None:
        self.spent_micro += micro

    @property
    def spent_usd(self) -> float:
        return self.spent_micro / 1e6
