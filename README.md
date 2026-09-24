# Implied-Volatility-Surface-from-SPX-Options
Implementation of an SPX options pricing pipeline using put-call parity, Black-Scholes, implied volatility, and volatility surface construction.

## Data
The data comes from OptionsDX, SPX options for 2023. We picked one day from each quarter (01-04, 06-30, 08-15, 11-14) and applied these filters:
- Big greater than 0 to drop dead quotes with no live market
- Implied volatility at or below 100%.
- Moneyness (strike/underlying price) between 0.75 and 1.25
- DTE < 365
- Missing volume values were set to 0, since a missing volume means no trades that day, not that the quote is bad.
These filters reduced the number of rows down from 53710 to 40703
