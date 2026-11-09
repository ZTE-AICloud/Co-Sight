// SPDX-License-Identifier: Apache-2.0
/**
 * @file DateTimePicker.tsx
 * @description A React component that provides a user-friendly interface for selecting both date and time. The component displays a button that shows the currently selected date and time in a human-readable format. When the button is clicked, a dropdown appears containing a calendar for date selection and an input for time selection. The component handles edge cases such as invalid dates and ensures that the dropdown is positioned correctly within the viewport. It also allows users to clear their selection easily. This component is designed to be reusable across the application wherever date and time input is required.
 */

import React, { useState, useRef, useEffect } from "react";
import { Calendar, Clock, ChevronLeft, ChevronRight, X } from "lucide-react";

interface DateTimePickerProps {
  value: string; // Expected format: YYYY-MM-DDTHH:mm
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  "aria-label"?: string;
  title?: string;
  /** Default time used when the user picks a date without a prior time
   *  selection. Defaults to 00:00 (midnight). Pass e.g. { hours: 23, minutes: 59 }
   *  for an "end of day" picker so the selected date is fully included. */
  defaultTime?: { hours: number; minutes: number };
}

export function DateTimePicker({
  value,
  onChange,
  placeholder = "Select date & time",
  className = "",
  "aria-label": ariaLabel,
  title,
  defaultTime,
}: DateTimePickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [alignment, setAlignment] = useState<"left" | "right">("left");
  const containerRef = useRef<HTMLDivElement>(null);

  // Parse value
  const dateObj = value ? new Date(value) : null;
  const [viewDate, setViewDate] = useState(dateObj || new Date());

  useEffect(() => {
    if (isOpen && containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect();
      if (rect.left + 230 > window.innerWidth) {
        setAlignment("right");
      } else {
        setAlignment("left");
      }
    }
  }, [isOpen]);

  useEffect(() => {
    if (dateObj && !isNaN(dateObj.getTime())) {
      setViewDate(dateObj);
    }
  }, [value]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const formatDisplay = (d: Date | null) => {
    if (!d || isNaN(d.getTime())) return "";
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const handleDateClick = (day: number) => {
    const newDate = new Date(viewDate.getFullYear(), viewDate.getMonth(), day);
    if (dateObj && !isNaN(dateObj.getTime())) {
      newDate.setHours(dateObj.getHours(), dateObj.getMinutes());
    } else {
      newDate.setHours(defaultTime?.hours ?? 0, defaultTime?.minutes ?? 0);
    }
    updateValue(newDate);
  };

  const handleTimeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const timeStr = e.target.value;
    if (!timeStr) return;
    const parts = timeStr.split(":");
    if (parts.length !== 2) return;
    const h = parts[0] || "0";
    const m = parts[1] || "0";
    const newDate = dateObj && !isNaN(dateObj.getTime()) ? new Date(dateObj) : new Date();
    newDate.setHours(parseInt(h, 10), parseInt(m, 10));
    updateValue(newDate);
  };

  const updateValue = (d: Date) => {
    const y = d.getFullYear();
    const mo = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    const h = String(d.getHours()).padStart(2, "0");
    const mi = String(d.getMinutes()).padStart(2, "0");
    onChange(`${y}-${mo}-${day}T${h}:${mi}`);
  };

  const clearValue = (e: React.MouseEvent) => {
    e.stopPropagation();
    onChange("");
    setIsOpen(false);
  };

  const daysInMonth = new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 0).getDate();
  const firstDayOfMonth = new Date(viewDate.getFullYear(), viewDate.getMonth(), 1).getDay();

  const days = [];
  for (let i = 0; i < firstDayOfMonth; i++) {
    days.push(<div key={`empty-${i}`} className="w-6 h-6" />);
  }
  for (let i = 1; i <= daysInMonth; i++) {
    const isSelected = !!(
      dateObj &&
      dateObj.getDate() === i &&
      dateObj.getMonth() === viewDate.getMonth() &&
      dateObj.getFullYear() === viewDate.getFullYear()
    );
    const isToday =
      new Date().getDate() === i &&
      new Date().getMonth() === viewDate.getMonth() &&
      new Date().getFullYear() === viewDate.getFullYear();

    days.push(
      <button
        key={i}
        type="button"
        onClick={() => handleDateClick(i)}
        className={`w-6 h-6 flex items-center justify-center rounded text-[11px] transition-colors
          ${
            isSelected
              ? "bg-indigo-500 text-white font-medium"
              : isToday
                ? "bg-indigo-100 text-indigo-700 font-medium"
                : "hover:bg-surface-3 text-muted hover:text-primary"
          }`}
      >
        {i}
      </button>
    );
  }

  const timeValue =
    dateObj && !isNaN(dateObj.getTime())
      ? `${String(dateObj.getHours()).padStart(2, "0")}:${String(dateObj.getMinutes()).padStart(2, "0")}`
      : "";

  return (
    <div className={`relative ${className}`} ref={containerRef}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        aria-label={ariaLabel}
        title={title}
        className={`flex items-center gap-2 bg-surface-1 border ${isOpen ? "border-indigo-300" : "border-border/50"} rounded px-2 py-1.5 min-w-[150px] text-xs focus:outline-none focus:border-indigo-300 transition-colors w-full text-left`}
      >
        <Calendar className="w-3.5 h-3.5 text-faint shrink-0" />
        <span className={`flex-1 truncate ${!dateObj ? "text-faint" : "text-tertiary"}`}>
          {dateObj ? formatDisplay(dateObj) : placeholder}
        </span>
        {dateObj && (
          <X className="w-3 h-3 text-faint hover:text-muted shrink-0" onClick={clearValue} />
        )}
      </button>

      {isOpen && (
        <div
          className={`absolute top-full mt-1 ${alignment === "right" ? "right-0" : "left-0"} z-50 bg-surface-1 border border-border/50 rounded-lg shadow-xl p-3 w-[220px] flex flex-col gap-3`}
        >
          {/* Calendar Header */}
          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={() =>
                setViewDate(new Date(viewDate.getFullYear(), viewDate.getMonth() - 1, 1))
              }
              className="p-1 hover:bg-surface-3 rounded text-faint hover:text-tertiary"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="text-xs font-medium text-tertiary">
              {viewDate.toLocaleString(undefined, { month: "long", year: "numeric" })}
            </span>
            <button
              type="button"
              onClick={() =>
                setViewDate(new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 1))
              }
              className="p-1 hover:bg-surface-3 rounded text-faint hover:text-tertiary"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          {/* Calendar Grid */}
          <div>
            <div className="grid grid-cols-7 gap-1 mb-1">
              {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map((day) => (
                <div key={day} className="w-6 text-center text-[10px] font-medium text-faint">
                  {day}
                </div>
              ))}
            </div>
            <div className="grid grid-cols-7 gap-1">{days}</div>
          </div>

          {/* Time Picker */}
          <div className="pt-3 border-t border-border/40 flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-faint">
              <Clock className="w-3.5 h-3.5" />
              <span className="text-[11px] font-medium">Time</span>
            </div>
            <input
              type="time"
              value={timeValue}
              onChange={handleTimeChange}
              className="bg-surface-2 border border-border/50 rounded px-2 py-1 text-xs text-tertiary focus:outline-none focus:border-indigo-300 w-[85px] time-input-custom"
            />
          </div>
        </div>
      )}
    </div>
  );
}
