#!/usr/bin/env Rscript
# Renders the GeoDB source-progress table for handoff (PDF + PNG) from the CSV that
# scripts/build_status_report.py writes. One canonical package (tinytable), notes in the
# image, reproducible from the script; never a hand-built Word table.
#
# Usage: Rscript scripts/render_progress_table.R <csv> <out_base> <stamp> <summary_line>

suppressPackageStartupMessages(library(tinytable))

args <- commandArgs(trailingOnly = TRUE)
csv_path <- args[1]
out_base <- args[2]
stamp <- if (length(args) >= 3) args[3] else format(Sys.Date())
summary_line <- if (length(args) >= 4) args[4] else ""

# TinyTeX lives under $HOME (the pod wipes /usr on restart), so put it on PATH explicitly.
Sys.setenv(PATH = paste(file.path(Sys.getenv("HOME"), ".TinyTeX/bin/x86_64-linux"),
                        Sys.getenv("PATH"), sep = ":"))

df <- read.csv(csv_path, check.names = FALSE, encoding = "UTF-8")

notes <- paste0(
  "Stand: ", stamp, ". ", summary_line,
  " Status: fertig = nichts offen; teilweise = eingebunden, vollstaendigerer Katalog erreichbar; ",
  "offen = manueller Schritt noetig. Verlinkungstiefe: Indikator/Tabelle = der Treffer oeffnet genau ",
  "die Groesse, Statistik/Datensatz = die enthaltende Einheit, Portal = Einstiegsseite. ",
  "Erzeugt aus scripts/build_status_report.py + scripts/render_progress_table.R."
)

# Source names and note text contain LaTeX specials (&, %, _) and symbols pdflatex has no
# glyph for, so escape the cells and fold the few symbols to ASCII first.
df[] <- lapply(df, function(column) {
  if (!is.character(column)) return(column)
  column <- gsub("\u2265", ">=", column, fixed = FALSE)
  column <- gsub("\u2264", "<=", column, fixed = FALSE)
  gsub("\u2019|\u2018", "'", column)
})
# Relative column widths: without them tabularray squeezes the long "next step" column
# into a sliver and the table grows to thousands of pixels tall.
# Column 2 needs room for single long German compounds ("Krankenhausverzeichnis"),
# which tabularray cannot break: too narrow and they overflow into the next column.
widths <- c(0.03, 0.265, 0.07, 0.04, 0.05, 0.135, 0.41)
if (ncol(df) != length(widths)) widths <- rep(1 / ncol(df), ncol(df))
t <- tt(df, notes = notes, width = widths)
t <- format_tt(t, escape = TRUE)
t <- style_tt(t, fontsize = 0.60)
t <- style_tt(t, i = 0, bold = TRUE)
t <- style_tt(t, j = c(1, 4, 5), align = "r")
t <- style_tt(t, j = c(2, 6, 7), align = "l")

save_tt(t, paste0(out_base, ".pdf"), overwrite = TRUE)
system2("/home/researcher/miniconda3/bin/pdftoppm",
        c("-png", "-r", "200", paste0(out_base, ".pdf"), out_base))
cat("wrote", paste0(out_base, ".pdf"), "\n")
