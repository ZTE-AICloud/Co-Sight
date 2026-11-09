// SPDX-License-Identifier: Apache-2.0
/**
 * @file Dropdown.tsx
 * @description 通用下拉框组件，用于选择智能体、模型、权限模式、思考强度等
 */

import { useState, useRef, useEffect } from "react";
import { ChevronDown, Check } from "lucide-react";
import { useTranslation } from "react-i18next";

export interface DropdownOption {
  id: string;
  name: string;
  description?: string;
}

interface DropdownProps {
  label: string;
  options: DropdownOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
  disabled?: boolean;
}

export function Dropdown({
  label,
  options,
  value,
  onChange,
  placeholder,
  required = false,
  disabled = false,
}: DropdownProps) {
  const { t } = useTranslation();
  const resolvedPlaceholder = placeholder ?? t("common:placeholders.selectPlaceholder");
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const selectedOption = options.find((opt) => opt.id === value);

  // 点击外部关闭下拉框
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // 键盘导航
  useEffect(() => {
    if (!isOpen) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  return (
    <div className="space-y-1.5" ref={dropdownRef}>
      <label className="block text-sm font-medium text-secondary">
        {label}
        {required && <span className="text-red-400 ml-1">*</span>}
      </label>

      <div className="relative">
        <button
          type="button"
          onClick={() => !disabled && setIsOpen(!isOpen)}
          disabled={disabled}
          className={`w-full flex items-center justify-between px-3 py-2 bg-surface-2 border border-border/50 rounded-lg text-left text-secondary transition-colors ${
            disabled
              ? "opacity-50 cursor-not-allowed"
              : "hover:border-accent/50 focus:border-accent focus:outline-none"
          }`}
        >
          <span className={selectedOption ? "text-primary" : "text-muted"}>
            {selectedOption ? selectedOption.name : resolvedPlaceholder}
          </span>
          <ChevronDown
            className={`w-4 h-4 text-muted transition-transform ${isOpen ? "rotate-180" : ""}`}
          />
        </button>

        {isOpen && (
          <div className="absolute z-[100] w-full mt-1 bg-surface-1 border border-border rounded-lg shadow-2xl max-h-60 overflow-y-auto">
            {options.map((option) => (
              <button
                key={option.id}
                type="button"
                onClick={() => {
                  onChange(option.id);
                  setIsOpen(false);
                }}
                className={`w-full flex items-center justify-between px-3 py-2.5 text-left hover:bg-surface-3 transition-colors first:rounded-t-lg last:rounded-b-lg ${
                  value === option.id ? "bg-accent/10" : ""
                }`}
              >
                <div className="flex-1 min-w-0">
                  <div className="text-primary text-sm font-medium">{option.name}</div>
                  {option.description && (
                    <div className="text-xs text-muted truncate mt-0.5">{option.description}</div>
                  )}
                </div>
                {value === option.id && (
                  <Check className="w-4 h-4 text-accent flex-shrink-0 ml-2" />
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
