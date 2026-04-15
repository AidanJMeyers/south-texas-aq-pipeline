# 15 — Recipes & Worked Examples

End-to-end worked examples for common research tasks. Each recipe names
the question it answers, the data it uses, the code to run, and the
shape of the output you should expect.

Recipes assume the pipeline has already been run and the outputs exist
under `data/`. If not, see [11_reproducibility.md](./11_reproducibility.md).

## Table of contents

- [Recipe 1: Which sites exceeded the 8-hr ozone NAAQS in 2023?](#recipe-1-which-sites-exceeded-the-8-hr-ozone-naaqs-in-2023)
- [Recipe 2: Multi-year ozone trend at a single site](#recipe-2-multi-year-ozone-trend-at-a-single-site)
- [Recipe 3: County-level PM₂.₅ seasonality](#recipe-3-county-level-pm25-seasonality)
- [Recipe 4: Temperature-pollution correlation at Camp Bullis](#recipe-4-temperature-pollution-correlation-at-camp-bullis)
- [Recipe 5: NAAQS exceedance dashboard table](#recipe-5-naaqs-exceedance-dashboard-table)
- [Recipe 6: Extract all VOC species measurements at CC Palm](#recipe-6-extract-all-voc-species-measurements-at-cc-palm)
- [Recipe 7: Spatial distribution of annual ozone (site-level)](#recipe-7-spatial-distribution-of-annual-ozone-site-level)
- [Recipe 8: Generate a Methods-section-ready summary of the data](#recipe-8-generate-a-methods-section-ready-summary-of-the-data)
- [Recipe 9: Cross-check our NAAQS numbers against EPA's published values](#recipe-9-cross-check-our-naaqs-numbers-against-epas-published-values)
- [Recipe 10: Build a shareable Parquet subset for a collaborator](#recipe-10-build-a-shareable-parquet-subset-for-a-collaborator)

---

## Recipe 1: Which sites exceeded the 8-hr ozone NAAQS in 2023?

**Question:** Which monitoring sites in the study area had a 4th-highest
daily max 8-hr rolling ozone average above 0.070 ppm in 2023?

**Data:** `data/csv/naaqs_design_values.csv`

=== "Python"

    ```python
    import pandas as pd

    dv = pd.read_csv("data/csv/naaqs_design_values.csv")
    exceedances = dv.query(
        "metric == 'ozone_8hr_4th_max' and year == 2023 and exceeds"
    ).sort_values("value", ascending=False)

    print(exceedances[["county_name", "site_name", "value", "naaqs_level"]])
    ```

=== "R"

    ```r
    library(data.table)
    dv <- fread("data/csv/naaqs_design_values.csv")
    exceedances <- dv[metric == "ozone_8hr_4th_max" & year == 2023 & exceeds == TRUE]
    setorder(exceedances, -value)
    print(exceedances[, .(county_name, site_name, value, naaqs_level)])
    ```

=== "SQL"

    ```sql
    SELECT county_name, site_name, value, naaqs_level
    FROM aq.naaqs_design_values
    WHERE metric = 'ozone_8hr_4th_max'
      AND year = 2023
      AND exceeds = TRUE
    ORDER BY value DESC;
    ```

**Expected output (abbreviated):**

| county_name | site_name                    | value  | naaqs_level |
|:-----------:|:-----------------------------|:------:|:-----------:|
| Comal       | City of Garden Ridge_0505    | 0.0769 | 0.070       |
| Bexar       | Heritage Middle School_0622  | 0.0761 | 0.070       |
| Bexar       | Camp Bullis_0052             | 0.0760 | 0.070       |
| Comal       | Bulverde Elementary_0503     | 0.0747 | 0.070       |
| Bexar       | San Antonio Northwest_0032   | 0.0745 | 0.070       |
| Bexar       | Calaveras Lake_0059          | 0.0714 | 0.070       |

All 6 of these sites are in the San Antonio–New Braunfels MSA, which is
formally in NAAQS nonattainment for the 8-hr ozone standard. Comal County
topping the list reflects the photochemistry — afternoon ozone plumes
drift downwind from central San Antonio.

---

## Recipe 2: Multi-year ozone trend at a single site

**Question:** How has ozone changed year-over-year at Camp Bullis
(AQSID 480290052) from 2015 to 2025?

**Data:** `data/csv/naaqs_design_values.csv`

=== "Python"

    ```python
    import pandas as pd
    import matplotlib.pyplot as plt

    dv = pd.read_csv("data/csv/naaqs_design_values.csv")
    bullis = dv.query(
        "aqsid == '480290052' and metric == 'ozone_8hr_4th_max'"
    ).sort_values("year")

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(bullis.year, bullis.value, marker="o", linewidth=2, color="#0c6e8a")
    ax.axhline(0.070, color="red", linestyle="--", label="NAAQS 0.070 ppm")
    ax.set_xlabel("Year")
    ax.set_ylabel("4th-highest daily max 8-hr O₃ (ppm)")
    ax.set_title("Camp Bullis — Ozone 8-hr Design Value, 2015–2025")
    ax.legend(loc="upper left")
    ax.grid(alpha=0.3)
    ax.set_ylim(0.055, 0.085)
    plt.tight_layout()
    plt.savefig("camp_bullis_ozone.png", dpi=150)
    plt.show()
    ```

=== "R"

    ```r
    library(data.table)
    library(ggplot2)

    dv <- fread("data/csv/naaqs_design_values.csv")
    bullis <- dv[aqsid == "480290052" & metric == "ozone_8hr_4th_max"]
    setorder(bullis, year)

    ggplot(bullis, aes(x = year, y = value)) +
      geom_line(color = "#0c6e8a", linewidth = 1.2) +
      geom_point(size = 3, color = "#0c6e8a") +
      geom_hline(yintercept = 0.070, color = "red", linetype = "dashed") +
      annotate("text", x = 2016, y = 0.071, label = "NAAQS 0.070 ppm",
               color = "red", hjust = 0) +
      scale_x_continuous(breaks = 2015:2025) +
      labs(title = "Camp Bullis — Ozone 8-hr Design Value, 2015–2025",
           x = "Year", y = "4th-highest daily max 8-hr O₃ (ppm)") +
      theme_minimal()

    ggsave("camp_bullis_ozone.png", width = 9, height = 5, dpi = 150)
    ```

---

## Recipe 3: County-level PM₂.₅ seasonality

**Question:** How does daily PM₂.₅ vary by season across the main study
counties?

**Data:** `data/csv/daily_pollutant_means.csv`

=== "Python"

    ```python
    import pandas as pd

    daily = pd.read_csv("data/csv/daily_pollutant_means.csv")

    pm25 = daily[
        (daily.pollutant_group == "PM2.5") &
        (daily.valid_day) &
        (daily.county_name.isin(["Bexar", "Nueces", "Cameron", "Hidalgo"]))
    ].copy()
    pm25["month"] = pd.to_datetime(pm25.date_local).dt.month
    pm25["season"] = pm25["month"].map({
        12: "DJF", 1: "DJF", 2: "DJF",
        3: "MAM", 4: "MAM", 5: "MAM",
        6: "JJA", 7: "JJA", 8: "JJA",
        9: "SON", 10: "SON", 11: "SON",
    })

    pivot = (pm25.groupby(["county_name", "season"])["mean"]
             .mean().round(2).unstack("season"))
    print(pivot[["DJF", "MAM", "JJA", "SON"]])
    ```

**Expected output (illustrative):**

| county_name | DJF   | MAM  | JJA   | SON   |
|:-----------:|:-----:|:----:|:-----:|:-----:|
| Bexar       | 8.10  | 9.15 | 10.50 | 8.80  |
| Cameron     | 9.25  | 9.40 | 9.10  | 9.00  |
| Hidalgo     | 9.80  | 10.20| 9.55  | 9.40  |
| Nueces      | 7.95  | 8.55 | 8.70  | 8.25  |

Summer (JJA) typically has the highest PM₂.₅ in Bexar due to photochemical
aerosol formation; Saharan dust intrusions in MAM–JJA push Rio Grande
Valley counties up.

---

## Recipe 4: Temperature-pollution correlation at Camp Bullis

**Question:** How strongly does daily temperature correlate with daily
ozone, PM₂.₅, and NO₂ at Camp Bullis?

**Data:** `data/csv/combined_aq_weather_daily.csv`

=== "Python"

    ```python
    import pandas as pd

    combined = pd.read_csv("data/csv/combined_aq_weather_daily.csv")
    site = combined.query("aqsid == '480290052' and valid_day").copy()

    results = {}
    for pollutant in ("Ozone", "PM2.5", "NOx_Family"):
        sub = site[site.pollutant_group == pollutant]
        if len(sub) > 100:
            r = sub[["mean", "temp_c", "humidity", "wind_speed"]].corr()
            results[pollutant] = r["mean"].round(3)

    print(pd.DataFrame(results))
    ```

**Expected output (illustrative):**

|             | Ozone  | PM2.5  | NOx_Family |
|:-----------:|:------:|:------:|:----------:|
| temp_c      | +0.62  | +0.18  | −0.35      |
| humidity    | −0.45  | +0.08  | +0.22      |
| wind_speed  | −0.28  | −0.20  | −0.40      |

Positive temperature correlation with ozone is the expected photochemistry
signal. Negative wind-speed correlation with NOx reflects dilution of
traffic emissions under calmer conditions.

---

## Recipe 5: NAAQS exceedance dashboard table

**Question:** Give me a year-by-year, pollutant-by-pollutant summary of
exceedances across the whole study area.

**Data:** `data/csv/naaqs_design_values.csv`

=== "Python"

    ```python
    import pandas as pd

    dv = pd.read_csv("data/csv/naaqs_design_values.csv")

    summary = (
        dv.groupby(["year", "metric"])
          .agg(n_sites=("aqsid", "nunique"),
               n_exceed=("exceeds", "sum"),
               max_val=("value", "max"),
               mean_val=("value", "mean"))
          .round(4)
          .reset_index()
          .query("metric.str.contains('p98|p99|4th_max|annual|exceedances')")
    )
    print(summary.to_string(index=False))
    ```

=== "SQL"

    ```sql
    SELECT year, metric,
           COUNT(DISTINCT aqsid)                         AS n_sites,
           SUM(CASE WHEN exceeds THEN 1 ELSE 0 END)      AS n_exceed,
           ROUND(MAX(value)::numeric, 4)                 AS max_val,
           ROUND(AVG(value)::numeric, 4)                 AS mean_val
    FROM aq.naaqs_design_values
    GROUP BY year, metric
    ORDER BY metric, year;
    ```

---

## Recipe 6: Extract all VOC species measurements at CC Palm

**Question:** What VOC species are being measured at Corpus Christi Palm,
and what are their typical concentrations?

**Data:** `data/parquet/pollutants/` (filter to VOCs partition)

=== "Python"

    ```python
    import pandas as pd

    vocs = pd.read_parquet(
        "data/parquet/pollutants",
        filters=[
            ("pollutant_group", "=", "VOCs"),
            ("aqsid", "=", "483550083"),
        ],
    )

    # The pollutant_name column uses "VOC_<parameter_code>" — you can map
    # each code to a species name via EPA's parameter list if desired.
    summary = (
        vocs.groupby("parameter_code")
            .agg(n_obs=("sample_measurement", "size"),
                 mean=("sample_measurement", "mean"),
                 p95=("sample_measurement", lambda s: s.quantile(0.95)),
                 max=("sample_measurement", "max"))
            .round(3)
            .reset_index()
            .sort_values("mean", ascending=False)
    )
    print(summary.head(20))
    ```

**Expected:** The top species by mean concentration at CC Palm typically
include ethane, propane, isopentane, and n-butane — all tracer gases for
fuel combustion and petrochemical activity, which matches the station's
proximity to the Port of Corpus Christi.

Full EPA parameter code → species name mapping is available at
https://aqs.epa.gov/aqsweb/documents/codetables/parameters.html.

---

## Recipe 7: Spatial distribution of annual ozone (site-level)

**Question:** Show me a site-level map of 2023 annual-peak 8-hr ozone.

**Data:** `data/csv/naaqs_design_values.csv` + `data/csv/site_registry.csv`

=== "Python"

    ```python
    import pandas as pd
    import matplotlib.pyplot as plt

    dv = pd.read_csv("data/csv/naaqs_design_values.csv")
    sites = pd.read_csv("data/csv/site_registry.csv", dtype={"aqsid": str})

    # Keep only active sites with coords
    sites = sites.query("data_status == 'active' and lat.notna()")

    o3_2023 = dv.query(
        "metric == 'ozone_8hr_4th_max' and year == 2023"
    ).merge(sites[["aqsid", "lat", "lon"]], on="aqsid")

    fig, ax = plt.subplots(figsize=(10, 8))
    sc = ax.scatter(
        o3_2023.lon, o3_2023.lat,
        c=o3_2023.value, cmap="RdYlBu_r",
        s=200, edgecolors="black", linewidth=0.8,
        vmin=0.050, vmax=0.080,
    )
    plt.colorbar(sc, ax=ax, label="Ozone 8-hr 4th-max (ppm)")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("South Texas 8-hr Ozone Design Values — 2023")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig("ozone_map_2023.png", dpi=150)
    ```

For a real choropleth or heatmap, feed the `(lat, lon, value)` tuples into
your kriging/IDW routine downstream of this pipeline.

---

## Recipe 8: Generate a Methods-section-ready summary of the data

**Question:** Print a one-paragraph summary of the pipeline's data
coverage suitable for inclusion in a manuscript Methods section.

**Data:** `data/csv/site_registry.csv` + `data/csv/daily_pollutant_means.csv`

=== "Python"

    ```python
    import pandas as pd

    sites = pd.read_csv("data/csv/site_registry.csv", dtype={"aqsid": str})
    daily = pd.read_csv("data/csv/daily_pollutant_means.csv")

    active = sites.query("data_status == 'active'")
    n_sites = len(active)
    n_counties = active["county_name"].nunique()
    n_epa = (active.network == "EPA").sum()
    n_tceq = (active.network == "TCEQ").sum()
    n_both = (active.network == "BOTH").sum()

    pm25 = daily[daily.pollutant_group == "PM2.5"]
    date_min = pm25.date_local.min()
    date_max = pm25.date_local.max()

    pollutants = sorted(daily.pollutant_group.unique())

    summary = (
        f"Ambient air quality data were assembled from {n_sites} active "
        f"monitoring sites across {n_counties} South Texas counties spanning "
        f"{date_min} to {date_max}. Sites were operated by the U.S. EPA "
        f"({n_epa}), TCEQ ({n_tceq}), or both networks ({n_both}). "
        f"Measured pollutants included {', '.join(pollutants)}. Hourly "
        f"observations were aggregated to daily statistics with a 75% "
        f"completeness threshold following 40 CFR §50."
    )
    print(summary)
    ```

---

## Recipe 9: Cross-check our NAAQS numbers against EPA's published values

**Question:** How do our computed NAAQS design values compare against
EPA's official published values for the same site-year?

**Approach:** Pull EPA's latest *Air Quality Design Values Report* (published
annually) from https://www.epa.gov/air-trends/air-quality-design-values
and compare row-by-row.

=== "Python"

    ```python
    import pandas as pd

    # Our computed values
    ours = pd.read_csv("data/csv/naaqs_design_values.csv")
    ours_2023_o3 = ours.query(
        "metric == 'ozone_8hr_4th_max' and year == 2023"
    )[["aqsid", "value"]].rename(columns={"value": "ours_ppm"})

    # EPA published — replace with your downloaded file
    # Columns should include AQSID + 8-hour O3 4th max per year
    # epa = pd.read_excel("epa_design_values_2023.xlsx", sheet_name="...")
    # epa = epa[["AQSID", "O3_4th_Max_ppm"]].rename(columns={"AQSID":"aqsid"})
    # merged = ours_2023_o3.merge(epa, on="aqsid", how="inner")
    # merged["diff_pct"] = (merged.ours_ppm - merged.O3_4th_Max_ppm) / merged.O3_4th_Max_ppm * 100
    # print(merged.sort_values("diff_pct", key=abs, ascending=False).head(10))
    ```

Expected differences are small (< 1%) for EPA-monitored sites where our
computation is a near-reproduction of EPA's methodology. Differences
larger than a few percent indicate completeness-rule interpretation
differences or timestamp boundary issues.

---

## Recipe 10: Build a shareable Parquet subset for a collaborator

**Question:** Send a collaborator a small Parquet file containing just
Bexar County PM₂.₅ daily means, without exposing the full data tree.

=== "Python"

    ```python
    import pandas as pd

    daily = pd.read_parquet(
        "data/parquet/daily/pollutant_daily.parquet"
    )
    subset = daily.query(
        "pollutant_group == 'PM2.5' and county_name == 'Bexar' and valid_day"
    )[["aqsid", "site_name", "date_local", "mean", "n_hours",
       "completeness_pct"]]

    subset.to_parquet("bexar_pm25_daily.parquet", index=False)
    print(f"Wrote {len(subset):,} rows to bexar_pm25_daily.parquet")
    ```

File size for a typical county × pollutant slice: **<5 MB**.
Easy to share over email or Slack.

---

## When you invent a new recipe

If you find yourself doing a query pattern more than twice, add it here.
Include:

1. A one-line question statement
2. The input files
3. Code in as many languages as are relevant (Python, R, SQL)
4. Expected output shape (even if approximate)
5. A short interpretive note — what the result means in context
