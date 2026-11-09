// SPDX-License-Identifier: Apache-2.0
/**
 * @file EventFiltersInfo.tsx
 * @description Accordion-style help panel that explains the Event Timeline's
 * status badges, the Pre/Post lifecycle, how filters compose, and what each
 * filter dropdown accepts. Rendered above the EventFilters toolbar on both
 * ActivityFeed and SessionDetail so users can discover the model without
 * leaving the page. Native <details> / <summary> — no popover primitive
 * required and keyboard-accessible out of the box.
 */

import { useTranslation } from "react-i18next";
import { Info } from "lucide-react";
import { AgentStatusBadge } from "./StatusBadge";

export function EventFiltersInfo() {
  const { t } = useTranslation("common");
  return (
    <details className="rounded-lg bg-surface-2 border border-border/50 overflow-hidden">
      <summary className="cursor-pointer select-none px-3 py-2 flex items-center text-[11px] text-faint hover:text-tertiary hover:bg-surface-3">
        <Info className="w-3.5 h-3.5 mr-2" />
        <span className="font-semibold uppercase tracking-wide mr-1.5">
          {t("eventFilters.help.title")}
        </span>
        <span className="text-faint font-normal">— {t("eventFilters.help.subtitle")}</span>
      </summary>

      <div className="divide-y divide-gray-200">
        <Section title={t("eventFilters.help.statusesTitle")}>
          <p className="text-[11px] text-faint mb-2">{t("eventFilters.help.statusesIntro")}</p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[11px] text-muted">
            <dt>
              <AgentStatusBadge status="working" />
            </dt>
            <dd className="self-center">{t("eventFilters.help.statusWorkingDesc")}</dd>
            <dt>
              <AgentStatusBadge status="waiting" />
            </dt>
            <dd className="self-center">{t("eventFilters.help.statusWaitingDesc")}</dd>
            <dt>
              <AgentStatusBadge status="completed" />
            </dt>
            <dd className="self-center">{t("eventFilters.help.statusCompletedDesc")}</dd>
            <dt>
              <AgentStatusBadge status="error" />
            </dt>
            <dd className="self-center">{t("eventFilters.help.statusErrorDesc")}</dd>
          </dl>
        </Section>

        <Section title={t("eventFilters.help.lifecycleTitle")}>
          <p className="text-[11px] text-faint mb-2">{t("eventFilters.help.lifecycleDesc")}</p>
          <code className="block bg-gray-900 border border-gray-700 rounded p-2 text-[11px] font-mono text-faint whitespace-pre-wrap">
            {t("eventFilters.help.lifecycleFlow")}
          </code>
        </Section>

        <Section title={t("eventFilters.help.filtersTitle")}>
          <ul className="list-disc pl-5 space-y-1 text-[11px] text-faint">
            <li>{t("eventFilters.help.filterTip1")}</li>
            <li>{t("eventFilters.help.filterTip2")}</li>
            <li className="text-amber-600">{t("eventFilters.help.filterTipGrouping")}</li>
            <li>{t("eventFilters.help.filterTip3")}</li>
            <li>{t("eventFilters.help.filterTip4")}</li>
          </ul>
        </Section>

        <Section title={t("eventFilters.help.valuesTitle")}>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[11px]">
            <Field label={t("eventFilters.status")} desc={t("eventFilters.help.valueStatusDesc")} />
            <Field
              label={t("eventFilters.eventType")}
              desc={t("eventFilters.help.valueEventTypeDesc")}
            />
            <Field
              label={t("eventFilters.toolName")}
              desc={t("eventFilters.help.valueToolNameDesc")}
            />
            <Field
              label={t("eventFilters.agentId")}
              desc={t("eventFilters.help.valueAgentIdDesc")}
            />
            <Field
              label={t("eventFilters.sessionId")}
              desc={t("eventFilters.help.valueSessionIdDesc")}
            />
            <Field
              label={t("eventFilters.searchPlaceholder")}
              desc={t("eventFilters.help.valueSearchDesc")}
            />
            <Field
              label={`${t("eventFilters.from")} / ${t("eventFilters.to")}`}
              desc={t("eventFilters.help.valueDateRangeDesc")}
            />
          </dl>
        </Section>
      </div>
    </details>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="group" open>
      <summary className="cursor-pointer select-none px-3 py-1.5 text-[11px] text-faint hover:bg-surface-3 flex items-center gap-2">
        <span className="text-faint transition-transform group-open:rotate-90">▶</span>
        <span className="font-semibold uppercase tracking-wide text-muted">{title}</span>
      </summary>
      <div className="px-3 pb-3 pt-1">{children}</div>
    </details>
  );
}

function Field({ label, desc }: { label: string; desc: string }) {
  return (
    <>
      <dt className="font-semibold text-faint whitespace-nowrap">{label}</dt>
      <dd className="text-faint">{desc}</dd>
    </>
  );
}
