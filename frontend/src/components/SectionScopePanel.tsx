import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { getUserSections, listPickerSections, setUserSections } from "../api/factory";

/** Section scope on the user access page (spec 1.1): all sections, or particular ones. */
export default function SectionScopePanel({ userId, editable }: { userId: number; editable: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = ["users", userId, "sections"];
  const scope = useQuery({ queryKey: key, queryFn: () => getUserSections(userId) });
  const sections = useQuery({ queryKey: ["sections"], queryFn: listPickerSections });
  const [all, setAll] = useState(true);
  const [chosen, setChosen] = useState<string[]>([]);
  useEffect(() => {
    if (scope.data) {
      setAll(scope.data.all_sections);
      setChosen(scope.data.sections);
    }
  }, [scope.data]);
  const save = useMutation({
    mutationFn: () => setUserSections(userId, all, all ? [] : chosen),
    onSuccess: (data) => queryClient.setQueryData(key, data),
  });

  if (!scope.data) return null;
  return (
    <section className="panel" aria-label={t("factory.sectionScope")}>
      <h2>{t("factory.sectionScope")}</h2>
      <p className="muted">{t("factory.sectionScopeHelp")}</p>
      <div className="checks">
        <label className="check">
          <input
            type="checkbox"
            checked={all}
            disabled={!editable}
            onChange={(e) => setAll(e.target.checked)}
          />
          {t("factory.allSections")}
        </label>
        {sections.data?.map((s) => (
          <label key={s.code} className="check">
            <input
              type="checkbox"
              checked={all || chosen.includes(s.code)}
              disabled={!editable || all}
              onChange={() =>
                setChosen((now) =>
                  now.includes(s.code) ? now.filter((c) => c !== s.code) : [...now, s.code],
                )
              }
            />
            {s.division} · {s.code} {s.name}
          </label>
        ))}
      </div>
      {editable && (
        <button type="button" disabled={save.isPending} onClick={() => save.mutate()}>
          {t("factory.saveSections")}
        </button>
      )}
      {save.isError && (
        <p className="form-error" role="alert">
          {save.error instanceof ApiError && save.error.detail
            ? save.error.detail
            : t("common.error")}
        </p>
      )}
    </section>
  );
}
