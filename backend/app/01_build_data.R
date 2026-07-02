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

print("Packages loaded successfully")

# ============================================================
# 1) Paths
# ============================================================
soep_dir <- "/home/ubuntu/destatis-rag/backend/app/data/soep_minimal"
issp_dir <- "/home/ubuntu/destatis-rag/backend/app/data/issp"
out_dir  <- "/home/ubuntu/destatis-rag/backend/app/data/outputs"
fig_dir  <- file.path(out_dir, "figures")
tab_dir  <- file.path(out_dir, "tables")

for (dir in c(out_dir, fig_dir, tab_dir)) {
  dir.create(dir, recursive = TRUE, showWarnings = FALSE)
}

print("Directories created")

# ============================================================
# 2) Helpers
# ============================================================
safe_read_data <- function(path) {
  ext <- tolower(tools::file_ext(path))
  tryCatch({
    if (ext == "rds")      readRDS(path)
    else if (ext == "sav") haven::read_sav(path)
    else if (ext == "dta") haven::read_dta(path)
    else                   NULL
  }, error = function(e) { message("Could not read: ", path, " — ", e$message); NULL })
}

as_num_clean <- function(v) {
  v <- as.numeric(v)
  v[v < 0] <- NA_real_
  v
}

to_label_chr <- function(v) {
  tolower(as.character(haven::as_factor(v)))
}

row_mean_index <- function(df, items, reverse = character()) {
  if (length(items) == 0) return(rep(NA_real_, nrow(df)))
  x <- lapply(df[items], as_num_clean)
  for (v in intersect(reverse, names(x))) x[[v]] <- 8 - x[[v]]
  mat <- as.matrix(as.data.frame(x))
  if (ncol(mat) == 0) return(rep(NA_real_, nrow(df)))

  # FIX: Scale across ALL individuals first, then average
  # This gives proper cross-person comparability
  mat_scaled <- scale(mat)  # scale across all rows (individuals)
  out <- rowMeans(mat_scaled, na.rm = TRUE)
  out[is.nan(out)] <- NA_real_
  out
}

first_existing <- function(x, candidates) {
  hit <- candidates[candidates %in% names(x)]
  if (length(hit) == 0) return(NA_character_)
  hit[1]
}

# Longitudinal weighting function (adapted from VegiSouep)
add_longitudinal_weights <- function(df,
                                     id_col = "pid",
                                     year_col = "syear",
                                     phrf_col = "phrf",
                                     pbleib_col = "pbleib",
                                     baseline_year = 2016L,
                                     baseline_col = "phrf_baseline",
                                     weight_col = "wt_long") {
  df <- df %>%
    arrange(.data[[id_col]], .data[[year_col]]) %>%
    group_by(.data[[id_col]]) %>%
    mutate(
      "{baseline_col}" := first(
        .data[[phrf_col]][
          .data[[year_col]] == baseline_year &
            is.finite(.data[[phrf_col]]) &
            .data[[phrf_col]] > 0
        ],
        default = NA_real_
      ),
      .transition_factor = lag(
        ifelse(
          is.finite(.data[[pbleib_col]]) & .data[[pbleib_col]] > 0,
          .data[[pbleib_col]],
          NA_real_
        ),
        default = 1
      ),
      "{weight_col}" := .data[[baseline_col]] * cumprod(.transition_factor)
    ) %>%
    ungroup() %>%
    select(-.transition_factor)
  df
}

# ============================================================
# 3) DIAGNOSTIC: Inspect what is actually in each SOEP file
# ============================================================
soep_files <- list.files(soep_dir, pattern = "\\.(rds|sav|dta)$",
                         full.names = TRUE, recursive = TRUE)
cat("\n=== SOEP FILE INVENTORY ===\n")
for (f in soep_files) {
  df <- safe_read_data(f)
  if (is.null(df)) next
  df <- janitor::clean_names(df)
  cat(sprintf("\n%s  [%d rows × %d cols]\n", basename(f), nrow(df), ncol(df)))
  cat("  pid/syear present:", all(c("pid","syear") %in% names(df)), "\n")
  key_groups <- list(
    demog    = c("sex","gebjahr","age","eastwest","bula","psample","migback"),
    employ   = c("pgemplst","pglabgro","pgnetto","pgisco","pgpsbil"),
    occ      = c("pgisei","pgisei08","pgisced","pgcedu","pgpsbil","pgbilzeit"),
    lifesat  = c("plh001"),
    loc_v2   = grep("^plh0(37[0-9]|38[0-9]|4[0-9][0-9])_v2", names(df), value=TRUE),
    loc_v1   = grep("^plh0(37[0-9]|38[0-9]|4[0-9][0-9])_v1", names(df), value=TRUE),
    loc_bare = grep("^plh0(37[0-9]|38[0-9]|4[0-9][0-9])$",   names(df), value=TRUE)
  )
  for (g in names(key_groups)) {
    found <- if (is.character(key_groups[[g]])) intersect(key_groups[[g]], names(df)) else key_groups[[g]]
    if (length(found) > 0) cat(sprintf("  [%s]: %s\n", g, paste(found, collapse=", ")))
  }
}
cat("\n===========================\n\n")

# ============================================================
# 4) Explicit SOEP file loading
# ============================================================
load_soep_file <- function(soep_dir, stem) {
  for (ext in c("rds","sav","dta")) {
    p <- file.path(soep_dir, paste0(stem, ".", ext))
    if (file.exists(p)) {
      df <- safe_read_data(p)
      if (!is.null(df)) {
        df <- janitor::clean_names(df)
        cat("Loaded:", stem, "—", nrow(df), "rows,", ncol(df), "cols\n")
        return(df)
      }
    }
  }
  message("WARNING: could not find file for stem: ", stem)
  NULL
}

ppathl  <- load_soep_file(soep_dir, "ppathl")   
pgen    <- load_soep_file(soep_dir, "pgen")     
pl      <- load_soep_file(soep_dir, "pl")       

# # ============================================================
# 5) Detect LoC items correctly (ONLY v2, no duplicates)
# ============================================================
if (!is.null(pl)) {
  loc_items <- grep("^plh0(379|380|381|382|383|384|385|386)_v2$", names(pl), value = TRUE)

  reverse_loc <- c(
    "plh0380_v2","plh0381_v2","plh0382_v2",
    "plh0384_v2","plh0385_v2","plh0386_v2"
  )

  cat("LoC items used:", paste(loc_items, collapse=", "), "\n")
} else {
  stop("pl.rds not found — cannot build LoC index")
}

# ============================================================
# 6) Build key variables from ppathl (Socialization-based East/West)
# ============================================================
if (is.null(ppathl)) stop("ppathl.rds not found — cannot proceed")

ppathl <- ppathl %>%
  mutate(
    pid   = as.integer(pid),
    syear = as.integer(syear)
  )

v_sex   <- first_existing(ppathl, c("sex"))
v_byear <- first_existing(ppathl, c("gebjahr", "birthyear"))
v_birth <- first_existing(ppathl, c("birthregion_ew", "birthregion", "loc1989", "corigin"))

cat("\nppathl key variables found:\n")
cat("  sex:", v_sex, "\n  birth_year:", v_byear, "\n  birth_region:", v_birth, "\n")

ppathl_slim <- ppathl %>%
  select(pid, syear, any_of(c(v_sex, v_byear, v_birth))) %>%
  mutate(
    # 1. Gender
    temp_sex = if (!is.na(v_sex)) .data[[v_sex]] else NA,
    sex_chr  = if (!is.na(v_sex)) to_label_chr(temp_sex) else NA_character_,
    female   = case_when(
      !is.na(sex_chr) & str_detect(sex_chr, "female|frau|weib") ~ 1L,
      !is.na(temp_sex) & temp_sex %in% c(2, "2") ~ 1L,
      TRUE ~ 0L
    ),
    
    # 2. Birth Year
    birth_year = if (!is.na(v_byear)) as.integer(.data[[v_byear]]) else NA_integer_,
    
    # 3. East/West Socialization via 1989 residence (pre-unification exposure)
    # This is the cleanest causal variable for East/West differences
    birth_val = if (!is.na(v_birth)) as.numeric(.data[[v_birth]]) else NA_real_,
    east_origin = case_when(
      # Use loc1989 (1989 residence) as primary indicator of pre-unification exposure
      v_birth == "loc1989" & birth_val == 2 ~ 1L,  # East Germany in 1989
      v_birth == "loc1989" & birth_val == 1 ~ 0L,  # West Germany in 1989
      # Fallback to birth region if loc1989 not available
      v_birth == "birthregion_ew" & birth_val == 22 ~ 1L,
      v_birth == "birthregion_ew" & birth_val == 21 ~ 0L,
      v_birth == "birthregion" & birth_val %in% 11:16 ~ 1L,
      v_birth == "birthregion" & birth_val %in% 1:10 ~ 0L,
      TRUE ~ NA_integer_
    )
  ) %>%
  select(pid, syear, female, birth_year, east_origin)

# [Remaining sections 7-14 stay the same as previous version]
# ============================================================
# 7) Build employment / income / education from pgen
# ============================================================
pgen_slim <- NULL
if (!is.null(pgen)) {
  pgen <- pgen %>%
    mutate(pid = as.integer(pid), syear = as.integer(syear))

  v_emp  <- first_existing(pgen, c("pgemplst", "employment_status", "emplst"))
  v_inc  <- first_existing(pgen, c("pglabgro", "pgnetto", "pglabnet", "income", "labor_income"))
  v_isei <- first_existing(pgen, c("pgisei08", "pgisei", "isei", "pgisei88"))
  v_edu  <- first_existing(pgen, c("pgisced11", "pgisced97", "pgisced", "isced", "pgenedu", "pgcedu"))

  cat("\npgen key variables found:\n")
  cat("  emp:", v_emp, " inc:", v_inc, " isei:", v_isei, " edu:", v_edu, "\n")
  
  pgen_cols <- c(v_emp, v_inc, v_isei, v_edu)
  pgen_cols <- pgen_cols[!is.na(pgen_cols)]

  pgen_slim <- pgen %>%
    select(pid, syear, any_of(pgen_cols)) %>%
    mutate(
      emp_chr   = if (!is.na(v_emp)) to_label_chr(.data[[v_emp]]) else NA_character_,
      unemployed = case_when(
        !is.na(emp_chr) & str_detect(emp_chr, "unemploy|arbeitslos|looking for work") ~ 1L,
        TRUE ~ 0L
      ),
      employed = case_when(
        !is.na(emp_chr) & str_detect(emp_chr, "employ|working|full.time|part.time|self.employ|selbst") ~ 1L,
        TRUE ~ 0L
      ),
      income    = if (!is.na(v_inc))  as_num_clean(.data[[v_inc]])  else NA_real_,
      log_income= ifelse(!is.na(income), log1p(pmax(income, 0)), NA_real_),
      isei      = if (!is.na(v_isei)) as_num_clean(.data[[v_isei]]) else NA_real_,
      educ      = if (!is.na(v_edu))  as_num_clean(.data[[v_edu]])  else NA_real_
    ) %>%
    select(pid, syear, unemployed, employed, income, log_income, isei, educ)
}

# ============================================================
# 8) Build LoC index (PCA — correct method)
# ============================================================
pl <- pl %>%
  mutate(pid = as.integer(pid), syear = as.integer(syear))

pl_slim <- pl %>%
  select(pid, syear, any_of(loc_items))

# clean + numeric
mat <- pl_slim %>%
  mutate(across(all_of(loc_items), as_num_clean))

# reverse coding
mat[reverse_loc] <- lapply(mat[reverse_loc], function(x) 8 - x)

# PCA index
loc_pca <- prcomp(mat[loc_items], scale. = TRUE)

pl_slim$loc_index <- loc_pca$x[,1]

pl_slim <- pl_slim %>%
  select(pid, syear, loc_index)

# ============================================================
# 9) Merge SOEP files (same as before)
# ============================================================
soep <- ppathl_slim %>%
  inner_join(pl_slim, by = c("pid", "syear"))

if (!is.null(pgen_slim)) {
  soep <- soep %>% left_join(pgen_slim, by = c("pid", "syear"))
}

soep <- soep %>%
  mutate(
    year = syear,
    age  = ifelse(!is.na(birth_year), year - birth_year, NA_integer_),
    cohort_group = cut(
      birth_year,
      breaks = c(-Inf, 1969, 1979, 1989, Inf),
      labels = c("<=1969", "1970-79", "1980-89", "1990+"),
      right  = TRUE
    )
  )

# ============================================================
# 🔴 CRITICAL: Restrict to LoC waves ONLY
# ============================================================
loc_waves <- c(1999, 2005, 2010, 2015, 2020)

soep <- soep %>%
  filter(year %in% loc_waves)

# ============================================================
# 10) Rebuild treatment aligned to LoC waves
# ============================================================
soep <- soep %>%
  arrange(pid, year) %>%
  group_by(pid) %>%
  mutate(
    # define any prior shock (cumulative)
    shock_between = as.integer(lag(cummax(shock_now), default = 0))
  ) %>%
  ungroup()

# ============================================================
# 11) Add longitudinal weights
# ============================================================
if ("phrf" %in% names(soep) && "pbleib" %in% names(soep)) {
  soep <- add_longitudinal_weights(soep, year_col = "year", baseline_year = 2016L)
  cat("\nLongitudinal weights added (phrf × cumulative pbleib).\n")
} else {
  soep$wt_long <- 1
  cat("\nNo weight variables found; using unweighted analysis.\n")
}

# ============================================================
# 11) Preflight diagnostic — catch NA problems before modelling
# ============================================================
cat("\n=== SOEP PREFLIGHT DIAGNOSTIC ===\n")
model_vars <- c("loc_index","pid","year","age","unemployed","female",
                "cohort_group","post_shock","birth_year","east_origin")
for (v in model_vars) {
  if (v %in% names(soep)) {
    n_na  <- sum(is.na(soep[[v]]))
    n_all <- nrow(soep)
    cat(sprintf("  %-20s  NA: %6d / %6d  (%.1f%%)\n",
                v, n_na, n_all, 100*n_na/n_all))
  } else {
    cat(sprintf("  %-20s  *** NOT IN DATA ***\n", v))
  }
}
cat("==================================\n\n")

# ============================================================
# 12) Build final panel (remove singletons!)
# ============================================================
soep_model <- soep %>%
  filter(!is.na(loc_index)) %>%
  group_by(pid) %>%
  filter(n() >= 2) %>%   # 🔴 THIS FIXES YOUR FE ERROR
  ungroup() %>%
  mutate(
    female       = as.integer(female),
    east_origin  = as.integer(east_origin),
    cohort_group = forcats::fct_drop(cohort_group)
  )

cat("Final panel rows:", nrow(soep_model), "\n")
cat("Unique individuals:", length(unique(soep_model$pid)), "\n")

saveRDS(soep_model, file.path(out_dir, "soep_model.rds"))

# ============================================================
# 13) ISSP
# ============================================================
load_data_folder <- function(path) {
  files <- list.files(path, pattern = "\\.(rds|sav|dta)$", full.names=TRUE, recursive=TRUE)
  if (length(files) == 0) return(list())
  objs <- lapply(files, safe_read_data)
  names(objs) <- make.names(tools::file_path_sans_ext(basename(files)), unique=TRUE)
  objs <- objs[!vapply(objs, is.null, logical(1))]
  lapply(objs, janitor::clean_names)
}

issp_list <- load_data_folder(issp_dir)

if (length(issp_list) > 0) {
  issp_names <- names(issp_list)
  cum_hit    <- issp_names[str_detect(tolower(issp_names), "8790|cum|cumulation|inequality")]
  issp       <- if (length(cum_hit) > 0) issp_list[[cum_hit[1]]] else issp_list[[1]]

  if ("country" %in% names(issp)) issp <- issp %>% filter(country == 276)
  if ("year"    %in% names(issp)) issp <- issp %>% mutate(year = as.integer(year))

  if ("c_sample" %in% names(issp)) {
    issp <- issp %>%
      mutate(
        c_sample_chr = as.character(c_sample),
        east_sample  = case_when(
          str_detect(c_sample_chr, "27602") ~ 1L,
          str_detect(c_sample_chr, "27601") ~ 0L,
          TRUE ~ NA_integer_
        )
      )
  } else {
    issp$east_sample <- NA_integer_
  }

  if ("sex" %in% names(issp)) {
    issp <- issp %>%
      mutate(
        sex_chr = to_label_chr(sex),
        female  = case_when(
          str_detect(sex_chr, "female|frau|weib") ~ 1L,
          sex %in% c(2, "2") ~ 1L,
          TRUE ~ 0L
        )
      )
  }

  merit_pos <- intersect(c("v3","v4","v5","v6"), names(issp))
  merit_neg <- intersect(c("v1","v7","v8"),      names(issp))

  if (length(c(merit_pos, merit_neg)) > 0) {
    issp <- issp %>% mutate(across(all_of(c(merit_pos, merit_neg)), as_num_clean))
    for (v in merit_neg) issp[[v]] <- 6 - issp[[v]]
    issp$merit_index <- rowMeans(
      scale(as.matrix(issp[, unique(c(merit_pos, merit_neg))])), na.rm=TRUE
    )
    issp$merit_index[is.nan(issp$merit_index)] <- NA_real_
  } else {
    issp$merit_index <- NA_real_
  }

  issp_germany <- issp %>% filter(!is.na(merit_index))
  saveRDS(issp_germany, file.path(out_dir, "issp_germany.rds"))
  cat("ISSP rows saved:", nrow(issp_germany), "\n")
} else {
  message("No ISSP files found under: ", issp_dir)
}

# ============================================================
# 14) Run log
# ============================================================
writeLines(c(
  paste0("Run date: ",        Sys.time()),
  paste0("soep_model rows: ", nrow(soep_model)),
  paste0("Outputs in: ",      out_dir)
), file.path(out_dir, "run_log_data.txt"))