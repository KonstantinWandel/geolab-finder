# =============================================================================
# 99_variable_discovery.R — SOEP/ISSP variable discovery (metadata only)
#
# Light-weight discovery: uses SOEP metadata JSON + file listing only.
# Does NOT load full RDS files to avoid memory/conversion issues.
#
# Usage:
#   Rscript 99_variable_discovery.R [patterns...]
#
# Outputs CSVs to: data/outputs/
# =============================================================================

suppressPackageStartupMessages({
  library(tidyverse)
  library(jsonlite, quietly = TRUE)
})

app_dir <- dirname(normalizePath(Sys.getenv("R_SCRIPT_PATH", unset = "./")))
if (!grepl("destatis-rag", app_dir, fixed = TRUE)) {
  app_dir <- dirname(getwd())
}

data_dir <- file.path(app_dir, "data")
issp_dir <- file.path(data_dir, "issp")
out_dir  <- file.path(data_dir, "outputs")
meta_json <- "/home/ubuntu/destatis-rag/soep_metadata_output/soep_metadata_enriched.json"

if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

# ── Helper: get file metadata without loading full data ─────────────────────
file_info <- function(path) {
  if (!file.exists(path)) return(NULL)
  size_mb <- round(file.size(path) / (1024^2), 1)
  tryCatch({
    # Only read dimensions and column names, not data
    df <- readRDS(path)
    if (!is.data.frame(df)) return(tibble(file = basename(path), rows = NA, cols = NA, size_mb = size_mb))
    tibble(
      file = basename(path),
      rows = nrow(df),
      cols = ncol(df),
      size_mb = size_mb,
      sample_cols_1_10 = paste(head(names(df), 10), collapse = ", ")
    )
  }, error = function(e) {
    tibble(file = basename(path), rows = NA, cols = NA, size_mb = size_mb)
  })
}

discover_files <- function(path) {
  if (!dir.exists(path)) return(character(0))
  list.files(path, pattern = "\\.rds$", full.names = TRUE, recursive = TRUE)
}

# ── Helper: load metadata JSON ────────────────────────────────────────────────
load_metadata <- function(path) {
  if (!file.exists(path)) {
    message("INFO: metadata JSON not found at ", path)
    return(NULL)
  }
  message("Loading metadata JSON...")
  tryCatch({
    meta <- fromJSON(path, flatten = TRUE)
    if (!is.data.frame(meta)) {
      message("WARNING: metadata JSON is not a data frame")
      return(NULL)
    }
    keep <- intersect(
      c("dataset", "variable_name", "label", "data_type", 
        "stats_summary", "sample_values", "value_labels", "rich_description"),
      names(meta)
    )
    meta %>% select(all_of(keep))
  }, error = function(e) {
    message("ERROR loading metadata: ", e$message)
    NULL
  })
}

# ── Main ──────────────────────────────────────────────────────────────────────
patterns <- commandArgs(trailingOnly = TRUE)
if (length(patterns) == 0) {
  patterns <- c(
    "pg", "plh", "pglabgro", "pgemplst", "psample", "birthregion", "east", "loc1989",
    "unemploy", "income", "educ", "sex", "bula"
  )
}

cat("=================================================================\n")
cat("99_variable_discovery.R\n")
cat("Patterns: ", paste(patterns, collapse = ", "), "\n")
cat("=================================================================\n\n")

# 1. File discovery
files <- c(discover_files(data_dir), discover_files(issp_dir))
if (length(files) > 0) {
  file_summary <- map_dfr(files, file_info)
  if (!is.null(file_summary) && nrow(file_summary) > 0) {
    write_csv(file_summary, file.path(out_dir, "variable_discovery_files.csv"))
    cat("File info saved: ", nrow(file_summary), " files\n\n")
    print(file_summary)
    cat("\n")
  }
}

# 2. Metadata discovery
meta <- load_metadata(meta_json)

if (!is.null(meta) && nrow(meta) > 0) {
  write_csv(meta, file.path(out_dir, "variable_discovery_metadata.csv"))
  cat("\nMetadata saved: ", nrow(meta), " rows\n")

  # 3. Filtered hits
  hit_regex <- paste(patterns, collapse = "|")
  meta_hits <- meta %>%
    filter(
      str_detect(variable_name, regex(hit_regex, ignore_case = TRUE)) |
      str_detect(label, regex(hit_regex, ignore_case = TRUE)) |
      str_detect(dataset, regex(hit_regex, ignore_case = TRUE))
    )

  if (nrow(meta_hits) > 0) {
    write_csv(meta_hits, file.path(out_dir, "variable_discovery_metadata_hits.csv"))
    cat("Metadata hits: ", nrow(meta_hits), " rows\n\n")
    cat("TOP HITS:\n")
    print(
      meta_hits %>%
      select(dataset, variable_name, label) %>%
      slice_head(n = 50)
    )
  } else {
    cat("No metadata hits found for patterns.\n")
  }
} else {
  cat("WARNING: metadata not loaded\n")
}

cat("\n=================================================================\n")
cat("Outputs saved to: ", out_dir, "\n\n")
