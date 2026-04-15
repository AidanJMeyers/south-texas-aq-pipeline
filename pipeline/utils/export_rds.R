# ============================================================================
# export_rds.R — Convert pipeline parquet/csv outputs to R-native .rds files.
#
# Invoked by pipeline/06_export_analysis_ready.py via subprocess. Writes three
# canonical RDS bundles into data/rds/. Uses data.table + arrow when available,
# falls back to base R otherwise.
# ============================================================================

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) {
  stop("Usage: Rscript export_rds.R <project_root>")
}
ROOT <- args[[1]]

cat(sprintf("[export_rds.R] ROOT = %s\n", ROOT))

have_arrow <- requireNamespace("arrow", quietly = TRUE)
have_dt    <- requireNamespace("data.table", quietly = TRUE)

if (have_dt) suppressPackageStartupMessages(library(data.table))

rds_dir <- file.path(ROOT, "data", "rds")
dir.create(rds_dir, showWarnings = FALSE, recursive = TRUE)

read_any <- function(parquet_path, csv_path) {
  if (have_arrow && dir.exists(parquet_path)) {
    arrow::read_parquet(parquet_path) |> as.data.frame()
  } else if (file.exists(csv_path)) {
    if (have_dt) data.table::fread(csv_path) else utils::read.csv(csv_path)
  } else {
    NULL
  }
}

save_bundle <- function(obj, out_name) {
  if (is.null(obj)) {
    cat(sprintf("[skip] %s — no source available\n", out_name))
    return(invisible(NULL))
  }
  out <- file.path(rds_dir, out_name)
  saveRDS(obj, out)
  cat(sprintf("[wrote] %s  (%d rows)\n", out, nrow(obj)))
}

# Pollutant daily master
poll_daily <- read_any(
  file.path(ROOT, "data", "parquet", "daily"),
  file.path(ROOT, "data", "csv", "daily_pollutant_means.csv")
)
save_bundle(poll_daily, "master_pollutant.rds")

# Weather master (prefer partitioned parquet; collapse to single frame)
wx <- NULL
wx_pq <- file.path(ROOT, "data", "parquet", "weather")
if (have_arrow && dir.exists(wx_pq)) {
  wx <- arrow::open_dataset(wx_pq) |> dplyr::collect() |> as.data.frame()
}
save_bundle(wx, "master_weather.rds")

# Combined daily
comb <- read_any(
  file.path(ROOT, "data", "parquet", "combined"),
  file.path(ROOT, "data", "csv", "combined_aq_weather_daily.csv")
)
save_bundle(comb, "combined_daily.rds")

cat("[export_rds.R] done\n")
