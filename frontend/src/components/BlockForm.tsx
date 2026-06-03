import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { DateTimePicker } from "@/components/DateTimePicker";

export interface BlockFormData {
  block_code: string;
  name: string;
  starts_at: string;
  ends_at: string;
  grace_period_minutes: number;
  priority: number;
  actor: string;
}

interface BlockFormProps {
  onSubmit: (data: BlockFormData) => Promise<void>;
}

export function BlockForm({ onSubmit }: BlockFormProps) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [gracePeriod, setGracePeriod] = useState(0);
  const [priority, setPriority] = useState(100);
  const [submitting, setSubmitting] = useState(false);

  const canSubmit = code.trim() && startsAt && endsAt && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      await onSubmit({
        block_code: code.trim(),
        name: name.trim() || code.trim(),
        starts_at: startsAt,
        ends_at: endsAt,
        grace_period_minutes: gracePeriod,
        priority,
        actor: "operator-ui",
      });
      setCode("");
      setName("");
      setStartsAt("");
      setEndsAt("");
      setGracePeriod(0);
      setPriority(100);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="grid gap-3 rounded-md border border-border/40 bg-background p-3 sm:grid-cols-2">
      {/* Code */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">
          {t("home.eventConfig.blockCodeLabel")}
          <span className="ml-1 text-destructive">*</span>
        </label>
        <input
          className="h-9 rounded-md border border-border bg-background px-3 text-sm"
          placeholder={t("home.eventConfig.blockCodePlaceholder")}
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
      </div>

      {/* Name */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">
          {t("home.eventConfig.blockNameLabel")}
        </label>
        <input
          className="h-9 rounded-md border border-border bg-background px-3 text-sm"
          placeholder={t("home.eventConfig.blockNamePlaceholder")}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      {/* Starts at */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">
          {t("home.eventConfig.startsAtLabel")}
          <span className="ml-1 text-destructive">*</span>
        </label>
        <DateTimePicker
          value={startsAt}
          onChange={setStartsAt}
          placeholder={t("home.eventConfig.startsAtPlaceholder")}
          className="w-full"
        />
      </div>

      {/* Ends at */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">
          {t("home.eventConfig.endsAtLabel")}
          <span className="ml-1 text-destructive">*</span>
        </label>
        <DateTimePicker
          value={endsAt}
          onChange={setEndsAt}
          placeholder={t("home.eventConfig.endsAtPlaceholder")}
          className="w-full"
        />
      </div>

      {/* Grace period */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">
          {t("home.eventConfig.gracePeriodLabel")}
        </label>
        <div className="flex items-center gap-2">
          <input
            className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm"
            type="number"
            min={0}
            max={120}
            value={gracePeriod}
            onChange={(e) => setGracePeriod(Number(e.target.value))}
          />
          <span className="shrink-0 text-xs text-muted-foreground">min</span>
        </div>
        <p className="text-xs text-muted-foreground">{t("home.eventConfig.gracePeriodHint")}</p>
      </div>

      {/* Priority */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-muted-foreground">
          {t("home.eventConfig.priorityLabel")}
        </label>
        <input
          className="h-9 w-full rounded-md border border-border bg-background px-3 text-sm"
          type="number"
          min={0}
          value={priority}
          onChange={(e) => setPriority(Number(e.target.value))}
        />
        <p className="text-xs text-muted-foreground">{t("home.eventConfig.priorityHint")}</p>
      </div>

      {/* Submit */}
      <div className="sm:col-span-2 flex justify-end">
        <Button
          className="h-9 px-5 text-sm"
          disabled={!canSubmit}
          onClick={() => void handleSubmit()}
        >
          {t("home.eventConfig.addBlock")}
        </Button>
      </div>
    </div>
  );
}
