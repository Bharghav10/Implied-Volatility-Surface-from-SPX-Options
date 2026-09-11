"""
Functions for working with CME SR1 / SOFR interest rates.
"""


def sr1_price_to_rate(price):
    """
    Convert an SR1 futures price into an implied
    interest rate.

    SR1 futures price convention:

        Implied rate (%) = 100 - futures price
    """

    return 100 - price
