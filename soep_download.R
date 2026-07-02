# install if needed (Positron/R)
# install.packages(c("dplyr", "purrr", "stringr", "arrow", "jsonlite", "tidyr"))

library(dplyr)
library(purrr)
library(stringr)
library(arrow)
library(jsonlite)
library(tidyr)

# -----------------------------
# 1. CONFIG
# -----------------------------

# Folder where your SOEP .rds files are stored
soep_path <- "/home/ubuntu/destatis-rag/backend/app/data"

# Output folder for metadata
output_path <- "/home/ubuntu/destatis-rag/soep_metadata_output"
dir.create(output_path, showWarnings = FALSE)

# Pattern to search for (all RDS files)
file_pattern <- "\\.rds$"

# -----------------------------
# 2. HELPER FUNCTIONS
# -----------------------------

# Safe NULL handler
`%||%` <- function(a, b) if (!is.null(a)) a else b

extract_variable_metadata <- function(df, file_name) {
  cat("  Scanning variables in:", file_name, "\n")
  
  var_names <- names(df)
  
  # Map over variables to extract rich metadata
  map_dfr(var_names, function(v) {
    col_data <- df[[v]]
    
    # Extract labels (typical for haven-imported or labeled SOEP data)
    var_label <- attr(col_data, "label") %||% attr(col_data, "variable.label") %||% ""
    
    # Extract value labels (mappings like 1 = "Very satisfied")
    val_labels <- attr(col_data, "labels") %||% attr(col_data, "value.labels")
    val_labels_str <- ""
    if (!is.null(val_labels)) {
      val_labels_str <- paste(
        paste0(val_labels, ": ", names(val_labels)),
        collapse = "; "
      )
    }
    
    # Basic Stats / Sample Data for LLM context
    sample_vals <- ""
    stats_summary <- ""
    
    try({
      if (is.numeric(col_data)) {
        non_missing <- col_data[!is.na(col_data) & col_data >= 0] # SOEP often uses negative for missing
        if (length(non_missing) > 0) {
          stats_summary <- paste0("Range: ", min(non_missing), " to ", max(non_missing), 
                                 ", Mean: ", round(mean(non_missing), 2))
        }
      } else {
        unique_vals <- head(unique(as.character(col_data)), 10)
        sample_vals <- paste(unique_vals, collapse = ", ")
      }
    }, silent = TRUE)

    tibble(
      dataset = str_remove(file_name, "\\.rds$"),
      variable_name = v,
      label = as.character(var_label),
      value_labels = val_labels_str,
      data_type = class(col_data)[1],
      stats_summary = stats_summary,
      sample_values = sample_vals,
      
      # Combined "Context" for LLM Embedding
      # This enables the RAG system to find variables based on descriptions or values
      embedding_context = paste0(
        "Variable: ", v, 
        "\nDescription: ", ifelse(var_label == "", "No description available", var_label),
        "\nDataset: ", file_name,
        "\nType: ", class(col_data)[1],
        ifelse(val_labels_str != "", paste0("\nCategories: ", val_labels_str), ""),
        ifelse(stats_summary != "", paste0("\nStats: ", stats_summary), ""),
        ifelse(sample_vals != "", paste0("\nExamples: ", sample_vals), "")
      )
    )
  })
}

# -----------------------------
# 3. EXECUTION
# -----------------------------

files <- list.files(
  soep_path,
  pattern = file_pattern,
  full.names = TRUE
)

if (length(files) == 0) {
  stop("No .rds files found in: ", soep_path)
}

cat("Found", length(files), "files. Extracting metadata...\n")

# Process files and combine
all_metadata <- map_dfr(files, function(f) {
  cat("Processing:", basename(f), "\n")
  df <- readRDS(f)
  
  # Handle cases where readRDS returns a list (e.g. from pyreadr)
  if (is.list(df) && !is.data.frame(df) && length(df) == 1) {
    df <- df[[1]]
  }
  
  if (!is.data.frame(df)) {
    warning("File ", basename(f), " is not a dataframe after loading. Skipping.")
    return(NULL)
  }
  
  extract_variable_metadata(df, basename(f))
})

# -----------------------------
# 4. EXPORT
# -----------------------------

cat("Saving results to:", output_path, "\n")

# 1. CSV (Human readable)
write.csv(all_metadata, file.path(output_path, "soep_metadata_registry.csv"), row.names = FALSE)

# 2. Parquet (High performance for FAISS/Python)
write_parquet(all_metadata, file.path(output_path, "soep_metadata_registry.parquet"))

# 3. JSON (Best for hierarchical/LLM context)
write_json(all_metadata, file.path(output_path, "soep_metadata_registry.json"), pretty = TRUE)

cat("\nSUCCESS: Metadata extracted for", length(unique(all_metadata$variable_name)), 
    "variables across", length(unique(all_metadata$dataset)), "datasets.\n")
cat("You can now load 'soep_metadata_registry.json' into your RAG pipeline.\n")


