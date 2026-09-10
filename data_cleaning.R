library(dplyr)
library(readr)
library(janitor)

# Read data from all 3 files
file_names <- list.files("spx_eod_2023q1-cfph7w/", full.names = T)
raw_data_df_list <- lapply(file_names, read_csv)
raw_data <- do.call(rbind, raw_data_df_list)


processed_df <- raw_data |> 
  clean_names() |> 
  filter(quote_date == "2023-01-04") |> 
  filter(
    # Expiry between 7 and 180
    dte >= 7 & dte <= 180,

    # Strikes within 20% of the index price
    strike_distance_pct <= 0.20,

    # Moneyness + Bid + IV filter:
    # - If Strike < Spot (OTM Put): ensure Put bid > 0 and Put IV is valid
    # - If Strike >= Spot (OTM Call): ensure Call bid > 0 and Call IV is valid
    if_else(
      strike < underlying_last,
      p_bid > 0 & !is.na(p_iv) & p_iv >= 0.05 & p_iv <= 1.50,
      c_bid > 0 & !is.na(c_iv) & c_iv >= 0.05 & c_iv <= 1.50
    )
  )

# Save
write_csv(processed_df, "spx_options_processed_2023-01-04.csv")
