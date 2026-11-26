import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { classNames } from "../../classes";
import type { AgentActivityStats } from "../../types";
import styles from "./ActivityChart.module.css";

const cx = classNames(styles);

export default function ActivityChart({
  stats,
}: {
  stats: AgentActivityStats;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !stats.hourly_distribution?.length) return;
    let chart: echarts.ECharts | null = null;
    try {
      chart = echarts.init(el);
      const hours = Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, "0")}`);
      const values = stats.hourly_distribution;
      chart.setOption({
        grid: { top: 14, right: 10, bottom: 24, left: 28 },
        tooltip: {
          trigger: "axis",
          formatter: (params: unknown) => {
            const list = Array.isArray(params) ? params : [params];
            const first = list[0] as { name?: string; value?: number } | undefined;
            if (!first) return "";
            return `${first.name}:00 时段 · ${first.value ?? 0} 条记录`;
          },
        },
        xAxis: {
          type: "category",
          data: hours,
          axisLine: { lineStyle: { color: "#e6e8eb" } },
          axisLabel: { color: "#9aa1ab", fontSize: 10, interval: 2 },
        },
        yAxis: {
          type: "value",
          minInterval: 1,
          splitLine: { lineStyle: { color: "#f1f3f6" } },
          axisLabel: { color: "#9aa1ab", fontSize: 10 },
        },
        series: [
          {
            type: "bar",
            data: values.map((v, idx) => ({
              value: v,
              itemStyle: {
                color: idx <= 4 || idx === 23 ? "#5a7ee6" : "#3565e0",
                borderRadius: [3, 3, 0, 0],
              },
            })),
            barMaxWidth: 14,
          },
        ],
      });
    } catch {
      /* JSDOM / canvas unavailable in unit test environment */
    }
    const ro =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => {
            chart?.resize();
          })
        : null;
    if (ro) ro.observe(el);
    return () => {
      ro?.disconnect();
      chart?.dispose();
    };
  }, [stats]);

  const peakLabel =
    stats.peak_hours && stats.peak_hours.length
      ? stats.peak_hours.map((h) => `${String(h).padStart(2, "0")}:00`).join(" / ")
      : "暂无高峰";

  return (
    <section className={`card ${cx("card")}`}>
      <div className={cx("header")}>
        <div className={cx("title")}>24 小时活跃作息分布</div>
        <div className={cx("sub")}>
          {stats.timezone_hint}
          {stats.date_span?.earliest
            ? ` · ${stats.date_span.earliest} ~ ${stats.date_span.latest}`
            : ""}
        </div>
      </div>

      <div className={cx("kpis")}>
        <div className={cx("kpi")}>
          <div className={cx("kpi-label")}>作息特征</div>
          <div className={cx("kpi-val")} title={stats.chronotype}>
            {stats.chronotype}
          </div>
        </div>
        <div className={cx("kpi")}>
          <div className={cx("kpi-label")}>活跃高峰</div>
          <div className={cx("kpi-val")} title={peakLabel}>
            {peakLabel}
          </div>
        </div>
        <div className={cx("kpi")}>
          <div className={cx("kpi-label")}>深夜活跃占比</div>
          <div className={cx("kpi-val")}>
            {`${Math.round((stats.late_night_ratio || 0) * 100)}%`}
          </div>
        </div>
        <div className={cx("kpi")}>
          <div className={cx("kpi-label")}>有效时间样本</div>
          <div className={cx("kpi-val")}>{`${stats.total_timed_events} 条`}</div>
        </div>
      </div>

      <div ref={containerRef} className={cx("chart")} />

      {(stats.top_languages?.length || stats.top_artists?.length) ? (
        <div className={cx("extra-tags")}>
          {(stats.top_languages || []).slice(0, 5).map((lang) => (
            <span key={`lang-${lang.name}`} className="chip">
              {lang.name} ({lang.count})
            </span>
          ))}
          {(stats.top_artists || []).slice(0, 5).map((artist) => (
            <span key={`artist-${artist.name}`} className="chip">
              ♪ {artist.name}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}
