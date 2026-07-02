# ============================================================
# 0) Packages
# ============================================================
pkgs <- c(
  "tidyverse", "haven", "janitor", "fixest", "broom", "modelsummary",
  "patchwork", "scales", "stringr", "purrr", "readr", "psych"
)

to_install <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]
if (length(to_install) > 0) install.packages(to_install, repos = "https://cloud.r-project.org")

invisible(lapply(pkgs, library, character.only = TRUE))

# ============================================================
# 1) Paths & load
# ============================================================
data_dir <- "/home/ubuntu/destatis-rag/backend/app/data"
out_dir  <- file.path(data_dir, "outputs")
fig_dir  <- file.path(out_dir, "figures")
tab_dir  <- file.path(out_dir, "tables")
for (dir in c(fig_dir, tab_dir)) dir.create(dir, recursive=TRUE, showWarnings=FALSE)

first_existing <- function(x, candidates) {
  hit <- candidates[candidates %in% names(x)]
  if (length(hit) == 0) return(NA_character_)
  hit[1]
}

soep_model_path  <- file.path(out_dir, "soep_model.rds")
issp_germany_path <- file.path(out_dir, "issp_germany.rds")

if (!file.exists(soep_model_path)) stop("Missing SOEP model data: run 01_build_data.R first.")

soep_model  <- readRDS(soep_model_path)
issp_germany <- if (file.exists(issp_germany_path)) readRDS(issp_germany_path) else NULL

# ============================================================
# 2) Preflight: show NA counts and decide which controls to use
# ============================================================
cat("\n=== SOEP_MODEL PREFLIGHT ===\n")
candidate_controls <- c("age", "unemployed", "female", "cohort_group",
                        "east_origin", "isei", "educ", "log_income")
avail_controls <- c()

for (v in candidate_controls) {
  if (v %in% names(soep_model)) {
    pct_na <- mean(is.na(soep_model[[v]])) * 100
    cat(sprintf("  %-20s  %.1f%% NA\n", v, pct_na))
    # Only use a control if it has real variation (< 95% NA)
    if (pct_na < 95) avail_controls <- c(avail_controls, v)
  } else {
    cat(sprintf("  %-20s  *** MISSING from data ***\n", v))
  }
}
cat("Controls to use:", paste(avail_controls, collapse=", "), "\n")
cat("Rows total:", nrow(soep_model), "\n")

# Check post_shock variation
n_treated <- sum(soep_model$post_shock == 1L, na.rm=TRUE)
cat("Treated (post_shock==1) rows:", n_treated, "\n")
cat("============================\n\n")

if (nrow(soep_model) == 0) stop("soep_model is empty — check 01_build_data.R output")
if (!"loc_index" %in% names(soep_model)) stop("loc_index missing from soep_model")

# ============================================================
# 3) FE model — CORRECTED (aligned panel)
# ============================================================

cat("\n=== MODEL DIAGNOSTICS ===\n")
cat("Observations:", nrow(soep_model), "\n")
cat("Individuals:", length(unique(soep_model$pid)), "\n")
cat("Mean obs per individual:", nrow(soep_model) / length(unique(soep_model$pid)), "\n")

# ============================================================
# MAIN FE MODEL (VALID NOW)
# ============================================================

m_fe <- feols(
  loc_index ~ shock_between + age + female | pid + year,
  cluster = ~pid,
  data = soep_model
)

print(summary(m_fe))

modelsummary(
  list("FE (LoC change)" = m_fe),
  output = file.path(tab_dir, "soep_fe_corrected.html")
)

cat("FE model saved.\n")

# ============================================================
# ROBUSTNESS: First-difference model (VERY IMPORTANT)
# ============================================================

soep_fd <- soep_model %>%
  arrange(pid, year) %>%
  group_by(pid) %>%
  mutate(
    d_loc = loc_index - lag(loc_index),
    d_shock = shock_between - lag(shock_between)
  ) %>%
  ungroup() %>%
  filter(!is.na(d_loc), !is.na(d_shock))

m_fd <- feols(
  d_loc ~ d_shock + age + female,
  cluster = ~pid,
  data = soep_fd
)

modelsummary(
  list("First Difference" = m_fd),
  output = file.path(tab_dir, "soep_fd.html")
)

cat("FD model saved.\n")

# ============================================================
# 4) Event study (Callaway-Sant'Anna via sunab) - WITH WEIGHTS
# ============================================================
fit_es <- function(dat, label) {
  dat <- dat %>% filter(!is.na(first_shock_year))
  if (nrow(dat) < 50) {
    message("Skipping event study for '", label, "' — too few treated obs (", nrow(dat), ")")
    return(NULL)
  }

  # Use longitudinal weights if available
  weight_arg <- if ("wt_long" %in% names(dat) && !all(is.na(dat$wt_long))) {
    paste0(", weights = ~wt_long")
  } else {
    ""
  }

  rhs <- paste(
    c("sunab(first_shock_year, year, ref.p=-1)", base_controls),
    collapse=" + "
  )
  fml <- as.formula(paste0("loc_index ~ ", rhs, " | pid + year"))

  cmd <- paste0("feols(fml, cluster=~pid", weight_arg, ", data=dat)")
  tryCatch(
    eval(parse(text=cmd)),
    error=function(e) { message("Event study failed for '", label, "': ", e$message); NULL }
  )
}

models_es <- list(
  male   = fit_es(filter(soep_model, female==0), "male"),
  female = fit_es(filter(soep_model, female==1), "female")
)
models_es <- models_es[!vapply(models_es, is.null, logical(1))]

if (length(models_es) > 0) {
  pdf(file.path(fig_dir, "soep_event_study_by_group.pdf"), width=10, height=8)
  oldpar <- par(no.readonly=TRUE); on.exit(par(oldpar), add=TRUE)
  par(mfrow=c(ceiling(length(models_es)/2), 2), mar=c(4,4,2,1))
  for (nm in names(models_es)) {
    iplot(models_es[[nm]], ref.line=0,
          xlab="Event time (waves relative to first shock)",
          ylab="Effect on LoC index", main=nm)
  }
  dev.off()
  cat("Event study plot saved.\n")
}

# ============================================================
# 5) Trend plot — SOEP (focus on East/West differences)
# ============================================================
group_vars <- intersect(c("year","female","cohort_group","east_origin"), names(soep_model))

trend_soep <- soep_model %>%
  group_by(across(all_of(group_vars))) %>%
  summarise(mean_loc=mean(loc_index, na.rm=TRUE), n=n(), .groups="drop") %>%
  mutate(
    female = factor(female, levels=c(0,1), labels=c("Men","Women")),
    east_origin = factor(east_origin, levels=c(0,1), labels=c("West","East"))
  )

p_trend_soep <- ggplot(trend_soep, aes(x=year, y=mean_loc)) +
  geom_line(linewidth=0.8) + geom_point(size=1.8)

if ("cohort_group" %in% names(trend_soep) && !all(is.na(trend_soep$cohort_group))) {
  p_trend_soep <- p_trend_soep + facet_grid(east_origin ~ cohort_group)
} else {
  p_trend_soep <- p_trend_soep + facet_wrap(~east_origin)
  message("cohort_group missing/all-NA: faceting by East/West only")
}

p_trend_soep <- p_trend_soep +
  scale_y_continuous(labels=label_number(accuracy=0.1)) +
  labs(x="Wave", y="Mean LoC index",
       title="SOEP: Locus of Control by wave, East/West origin, cohort") +
  theme_minimal(base_size=12) +
  theme(legend.position="bottom")

ggsave(file.path(fig_dir, "soep_trend_east_west.pdf"), p_trend_soep, width=12, height=8)
ggsave(file.path(fig_dir, "soep_trend_east_west.png"), p_trend_soep, width=12, height=8, dpi=300)
cat("SOEP East/West trend plot saved.\n")

# ============================================================
# 6) ISSP models and figures
# ============================================================
if (!is.null(issp_germany)) {
  rhs_issp <- intersect(c("east_sample","female","cohort_group"), names(issp_germany))
  rhs_issp <- rhs_issp[vapply(rhs_issp, function(v) mean(is.na(issp_germany[[v]])) < 0.95, logical(1))]
  fml_issp <- as.formula(paste0("merit_index ~ ", paste(rhs_issp, collapse=" + ")))

  w_var <- first_existing(issp_germany, c("weight","wt","dweight","design_weight"))
  m_issp <- if (!is.na(w_var)) {
    feols(fml_issp, data=issp_germany, weights=as.formula(paste0("~", w_var)))
  } else {
    feols(fml_issp, data=issp_germany)
  }

  modelsummary(list("ISSP validation"=m_issp),
               output=file.path(tab_dir, "issp_validation.html"))
  cat("ISSP model table saved.\n")

  trend_issp <- issp_germany %>%
    group_by(year, east_sample, female) %>%
    summarise(mean_merit=mean(merit_index, na.rm=TRUE), n=n(), .groups="drop") %>%
    mutate(
      east_sample = factor(east_sample, levels=c(0,1), labels=c("West","East")),
      female      = factor(female,      levels=c(0,1), labels=c("Men","Women"))
    )

  p_trend_issp <- ggplot(trend_issp, aes(x=year, y=mean_merit,
                                         color=east_sample, group=east_sample)) +
    geom_line(linewidth=0.8) + geom_point(size=1.8) +
    facet_wrap(~female) +
    scale_y_continuous(labels=label_number(accuracy=0.1)) +
    labs(x="ISSP year", y="Mean meritocracy index", color="Sample",
         title="ISSP Germany: meritocracy beliefs by wave, East/West, gender") +
    theme_minimal(base_size=12) + theme(legend.position="bottom")

  ggsave(file.path(fig_dir, "issp_trend_by_group.pdf"), p_trend_issp, width=12, height=8)
  ggsave(file.path(fig_dir, "issp_trend_by_group.png"), p_trend_issp, width=12, height=8, dpi=300)
  cat("ISSP trend plot saved.\n")
}

# ============================================================
# 7) Run log
# ============================================================
writeLines(c(
  paste0("Run date: ", Sys.time()),
  paste0("SOEP model rows: ", nrow(soep_model)),
  paste0("Controls used: ",   paste(avail_controls, collapse=", ")),
  paste0("ISSP rows: ",       if (!is.null(issp_germany)) nrow(issp_germany) else 0),
  paste0("Outputs in: ",      out_dir)
), file.path(out_dir, "run_log_models.txt"))