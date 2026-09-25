# Value labels and a distribution summary for every SOEP-Core v41 variable, read from the data
# files themselves.
#
#   OPENBLAS_NUM_THREADS=1 Rscript scripts/extract_soep_v41_value_labels.R
#
# Why this exists: the official metadata on GitHub (paneldata/soep-core, the source of
# build_soep_v41_metadata.py) publishes no value labels at all. Its `categories` columns are empty
# in v41 and were already empty at the v40.0 tag. Until 2026-09-26 the finder therefore carried
# value labels over from the old v40 corpus, which covered 22,097 variables and left the rest,
# including every raw wave file, without categories. The v41 .rds files carry the labels for
# every labelled column, so they are read here directly.
#
# Output: soep_metadata_output/soep_v41_rds_labels.tsv (git-ignored, like every metadata file)
#   dataset, variable, var_label, value_labels ("code: label; ..."), stats ("Range: a to b, Mean: m")
# The statistics are computed over valid codes only (>= 0), in the format the index already uses.
# No microdata leaves this script: one summary line per variable, nothing per person.

args <- commandArgs(trailingOnly = TRUE)
here <- normalizePath(dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE))))
repo <- dirname(here)
src <- Sys.getenv("SOEP_V41_DIR", "/home/researcher/kwandel/soep_data/v41eu_r_de/R_DE/soepdata")
out <- file.path(repo, "soep_metadata_output", "soep_v41_rds_labels.tsv")
cores <- as.integer(Sys.getenv("EXTRACT_CORES", "32"))

files <- list.files(src, pattern = "\\.rds$", recursive = TRUE, full.names = TRUE)
if (length(files) < 600) stop(sprintf("expected about 615 .rds files under %s, found %d", src, length(files)))

num <- function(v) ifelse(v == round(v), sprintf("%.0f", v), sprintf("%.6g", v))
flat <- function(s) gsub("[\t\r\n]+", " ", s)

one_file <- function(path) {
  x <- readRDS(path)
  ds <- tolower(sub("\\.rds$", "", basename(path)))
  rows <- lapply(names(x), function(var) {
    col <- x[[var]]
    lab <- attr(col, "label", exact = TRUE)
    vl <- attr(col, "labels", exact = TRUE)
    labels <- ""
    if (!is.null(vl) && length(vl)) {
      codes <- as.numeric(unclass(vl))
      o <- order(codes)
      labels <- paste(paste0(num(codes[o]), ": ", names(vl)[o]), collapse = "; ")
    }
    stats <- ""
    if (is.numeric(unclass(col))) {
      v <- as.numeric(unclass(col))
      v <- v[!is.na(v) & v >= 0]
      if (length(v)) stats <- sprintf("Range: %s to %s, Mean: %.2f", num(min(v)), num(max(v)), mean(v))
    }
    data.frame(dataset = ds, variable = tolower(var), var_label = flat(if (is.null(lab)) "" else lab),
               value_labels = flat(labels), stats = stats, stringsAsFactors = FALSE)
  })
  rm(x); gc(FALSE)
  do.call(rbind, rows)
}

# Largest files first, so the long tail of small raw files fills in behind them.
files <- files[order(-file.size(files))]
parts <- parallel::mclapply(files, function(p) tryCatch(one_file(p), error = function(e) {
  message("FEHLER ", p, ": ", conditionMessage(e)); NULL
}), mc.cores = cores, mc.preschedule = FALSE)
failed <- sum(vapply(parts, is.null, TRUE))
res <- do.call(rbind, parts)
if (failed > 0) stop(sprintf("%d files could not be read; nothing written", failed))
if (nrow(res) < 120000) stop(sprintf("expected about 125,000 variables, got %d", nrow(res)))
res <- res[order(res$dataset, res$variable), ]
write.table(res, out, sep = "\t", quote = FALSE, row.names = FALSE, fileEncoding = "UTF-8")
cat(sprintf("%d variables from %d files -> %s\n  with value labels: %d\n  with statistics: %d\n",
            nrow(res), length(files), out, sum(res$value_labels != ""), sum(res$stats != "")))
