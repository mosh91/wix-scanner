import * as React from "react";
import { format, parse, isValid } from "date-fns";
import { CalendarIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

interface DateTimePickerProps {
  value: string; // "YYYY-MM-DDTHH:mm"
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}

function parseLocalDatetime(raw: string): { date: Date | undefined; time: string } {
  if (!raw) return { date: undefined, time: "00:00" };
  const [datePart, timePart = "00:00"] = raw.split("T");
  const parsed = parse(datePart, "yyyy-MM-dd", new Date());
  return { date: isValid(parsed) ? parsed : undefined, time: timePart.slice(0, 5) };
}

function toLocalDatetime(date: Date | undefined, time: string): string {
  if (!date || !isValid(date)) return "";
  return `${format(date, "yyyy-MM-dd")}T${time}`;
}

export function DateTimePicker({ value, onChange, placeholder, className }: DateTimePickerProps) {
  const [open, setOpen] = React.useState(false);
  const { date, time } = parseLocalDatetime(value);

  const handleDaySelect = (day: Date | undefined) => {
    onChange(toLocalDatetime(day, time));
    if (day) setOpen(false);
  };

  const handleTimeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange(toLocalDatetime(date, e.target.value));
  };

  const label = date
    ? `${format(date, "MMM d, yyyy")} ${time}`
    : null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className={cn(
            "h-9 justify-start gap-2 text-left text-sm font-normal",
            !label && "text-muted-foreground",
            className,
          )}
        >
          <CalendarIcon className="size-4 shrink-0" />
          {label ?? placeholder ?? "Pick date & time"}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="single"
          selected={date}
          onSelect={handleDaySelect}
          captionLayout="dropdown"
          initialFocus
        />
        <div className="flex items-center gap-2 border-t border-border/60 px-3 py-2">
          <label className="text-xs text-muted-foreground">Time</label>
          <input
            type="time"
            className="h-8 flex-1 rounded border border-border bg-background px-2 text-sm"
            value={time}
            onChange={handleTimeChange}
          />
        </div>
      </PopoverContent>
    </Popover>
  );
}
