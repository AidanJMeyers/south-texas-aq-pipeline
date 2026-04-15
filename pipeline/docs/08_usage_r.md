# 08 — R / RStudio Usage Guide

Loading pipeline outputs in R. Three paths: **parquet (fast)**, **CSV
(universal)**, **RDS (R-native)**. All three contain the same data with
identical column names.

## Install

```r
install.packages(c("arrow", "data.table", "dplyr", "ggplot2"))
# Optional for Postgres:
install.packages(c("DBI", "RPostgres"))
```

`arrow` is the key dependency for the fast path. If it fails to install on
your platform, fall back to `data.table::fread()` on the CSV files.

## Parquet — the fast path

```r
library(arrow)
library(dplyr)

# Lazy-load the dataset — no data actually loaded yet
pollutants <- open_dataset("data/parquet/pollutants/")

# Compose a query; the predicates push down to Arrow
bexar_o3_2023 <- pollutants |>
  filter(pollutant_group == "Ozone",
         county_name    == "Bexar",
         year           == 2023) |>
  select(aqsid, site_name, date_local, time_local, sample_measurement) |>
  collect()

cat(nrow(bexar_o3_2023), "rows loaded\n")
```

`collect()` is when the data actually materializes in memory. Keep as much
filtering upstream of `collect()` as possible.

### Load a full year in one shot

```r
library(arrow)
all_2023 <- open_dataset("data/parquet/pollutants/") |>
  filter(year == 2023) |>
  collect()
```

### Daily aggregates

```r
daily <- arrow::read_parquet("data/parquet/daily/pollutant_daily.parquet")
daily_valid <- daily[daily$valid_day, ]
```

## CSV — the universal path

```r
library(data.table)

daily <- fread("data/csv/daily_pollutant_means.csv")
naaqs <- fread("data/csv/naaqs_design_values.csv")
combined <- fread("data/csv/combined_aq_weather_daily.csv")
sites <- fread("data/csv/site_registry.csv")
```

`fread` is ~5× faster than base R `read.csv` and handles type inference
correctly.

## RDS — optional R-native path

If step 06 successfully shelled out to Rscript at pipeline run time, these
bundles exist:

```r
master_pollutant <- readRDS("data/rds/master_pollutant.rds")
master_weather   <- readRDS("data/rds/master_weather.rds")
combined_daily   <- readRDS("data/rds/combined_daily.rds")
```

These are identical to the parquet outputs but load slightly faster from
R and preserve factor levels.

## Full worked example: ggplot ozone exceedances by county

```r
library(data.table)
library(ggplot2)

dv <- fread("data/csv/naaqs_design_values.csv")

# Filter to ozone 8-hr 4th-max and classify each row
o3 <- dv[metric == "ozone_8hr_4th_max"]
o3[, status := fifelse(exceeds, "Exceeds", "Under")]

ggplot(o3, aes(x = year, y = value, color = county_name, shape = status)) +
  geom_point(size = 3, alpha = 0.75) +
  geom_hline(yintercept = 0.070, linetype = "dashed", color = "red") +
  labs(
    title = "South Texas Ozone 8-hr Design Values, 2015–2025",
    subtitle = "Red line = NAAQS 0.070 ppm",
    x = "Year", y = "4th-highest daily max 8-hr mean (ppm)",
    color = "County", shape = "Status"
  ) +
  theme_minimal() +
  theme(legend.position = "right")

ggsave("ozone_design_values.png", width = 10, height = 6, dpi = 150)
```

## Joining pollutant with weather

```r
library(data.table)

combined <- fread("data/csv/combined_aq_weather_daily.csv")

# Monthly means of ozone vs temperature at a single site
site <- combined[aqsid == "480290052" & pollutant_group == "Ozone"]
site[, ym := substr(date_local, 1, 7)]

monthly <- site[, .(
  mean_o3 = mean(mean, na.rm = TRUE),
  mean_temp = mean(temp_c, na.rm = TRUE)
), by = ym][order(ym)]

print(head(monthly, 12))
```

## Site registry lookup

```r
library(data.table)

sites <- fread("data/csv/site_registry.csv")

# Just active sites with their weather station pair
active <- sites[data_status == "active"]
cat(nrow(active), "active sites\n")
print(table(active$county_name, active$network))
```

## Updating legacy notebooks

The project's existing R notebooks (`AM_R_Notebooks/NB1_*.R`, `NB2_*.R`,
`NB3_*.R`) still load from `01_Data/Processed/*.csv`. To migrate to the
pipeline outputs:

**Before:**
```r
ozone <- fread("01_Data/Processed/By_Pollutant/Ozone_AllCounties_2015_2025.csv")
pm25  <- fread("01_Data/Processed/By_Pollutant/PM2.5_AllCounties_2015_2025.csv")
# ... etc ...
```

**After (parquet, preferred):**
```r
library(arrow)
all_poll <- open_dataset("data/parquet/pollutants/")
ozone <- all_poll |> filter(pollutant_group == "Ozone") |> collect()
pm25  <- all_poll |> filter(pollutant_group == "PM2.5") |> collect()
```

**After (CSV fallback):**
```r
daily <- fread("data/csv/daily_pollutant_means.csv")
ozone <- daily[pollutant_group == "Ozone"]
```

The schemas match, so downstream code rarely needs changes beyond the load
line.

## Postgres from R (optional)

```r
library(DBI)
library(RPostgres)

conn <- dbConnect(
  RPostgres::Postgres(),
  dbname   = "neondb",
  host     = "ep-xxx.us-east-2.aws.neon.tech",
  user     = "neondb_owner",
  password = Sys.getenv("PGPASSWORD"),
  sslmode  = "require"
)

dv <- dbGetQuery(conn, "
  SELECT county_name, AVG(value) AS mean_val
  FROM aq.naaqs_design_values
  WHERE metric = 'ozone_8hr_4th_max' AND year = 2023
  GROUP BY county_name
  ORDER BY mean_val DESC
")

dbDisconnect(conn)
```

Store the password in `.Renviron` so it's not in R scripts:

```
# ~/.Renviron
PGPASSWORD=your_neon_password_here
```

See [10_usage_sql.md](./10_usage_sql.md) for more query examples.

## Troubleshooting

**`arrow::open_dataset()` is slow on OneDrive:** OneDrive files are
virtualized and first-access is slow. Copy `data/parquet/` to a local
non-synced folder for hot-loop development.

**Factor levels lost on CSV round-trip:** Use `RDS` bundles if factor
ordering matters for plots.

**`fread` returns `integer64` for `n_hours`:** Add `integer64 = "numeric"`
to the `fread` call.
