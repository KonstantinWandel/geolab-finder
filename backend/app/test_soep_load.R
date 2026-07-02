library(tidyverse)
library(haven)
library(janitor)

soep_dir <- "/home/ubuntu/destatis-rag/backend/app/data/soep_minimal"

safe_read_data <- function(path) {
  ext <- tolower(tools::file_ext(path))
  tryCatch({
    if (ext == "rds") {
      readRDS(path)
    } else if (ext == "sav") {
      haven::read_sav(path)
    } else if (ext == "dta") {
      haven::read_dta(path)
    } else {
      NULL
    }
  }, error = function(e) NULL)
}

standardize_names <- function(x) {
  if (!inherits(x, "data.frame")) return(x)
  janitor::clean_names(x)
}

load_data_folder <- function(path) {
  files <- list.files(path, pattern = "\\.(rds|sav|dta)$", full.names = TRUE, recursive = TRUE)
  if (length(files) == 0) return(list())
  objs <- lapply(files, safe_read_data)
  names(objs) <- make.names(tools::file_path_sans_ext(basename(files)), unique = TRUE)
  objs <- objs[!vapply(objs, is.null, logical(1))]
  lapply(objs, standardize_names)
}

needed_vars <- c(
  "pid", "syear", "hid", "cid", "east_origin", "female", "age", "income", "edu_years", "unemployed", "income_drop_30pct",
  "plh0379", "plh0379_v2", "plh0380", "plh0380_v2", "plh0381", "plh0381_v2", 
  "plh0382", "plh0382_v2", "plh0383", "plh0383_v2", "plh0384", "plh0384_v2", 
  "plh0385", "plh0385_v2", "plh0386", "plh0386_v2"
)

load_data_select <- function(path, vars) {
  files <- list.files(path, pattern = "\\.(rds|sav|dta)$", full.names = TRUE, recursive = TRUE)
  if (length(files) == 0) return(list())
  objs <- lapply(files, function(f) {
    print(paste("Loading", f))
    obj <- safe_read_data(f)
    if (is.null(obj)) return(NULL)
    present_vars <- intersect(names(obj), vars)
    if (length(present_vars) == 0) return(NULL)
    obj[, present_vars, drop = FALSE]
  })
  objs <- objs[!vapply(objs, is.null, logical(1))]
  names(objs) <- make.names(tools::file_path_sans_ext(basename(files)), unique = TRUE)
  lapply(objs, standardize_names)
}

print("Starting SOEP load")
soep_objs <- load_data_select(soep_dir, needed_vars)
print("SOEP loaded, length:", length(soep_objs))