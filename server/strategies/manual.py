from .base import Strategy


class ManualStrategy(Strategy):
    name = "manual"
    label = "Manual"
    description = "No automated trading. Use the manual order panel only."
    default_params: dict = {}
    auto_trade = False
    hidden = True

    def evaluate(self, positions):
        return []
