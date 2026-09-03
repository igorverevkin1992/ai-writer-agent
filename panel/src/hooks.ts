import { useCallback, useRef, useState } from "react";

export type RunPending = <T>(fn: () => Promise<T>) => Promise<T | undefined>;

/** Pending-состояние кнопок (аудит 5.4): пока запрос идёт, кнопка disabled,
 *  а повторный клик (двойной клик, Enter) игнорируется — ref срабатывает
 *  раньше, чем React успеет перерисовать disabled. */
export function usePending(): [boolean, RunPending] {
  const [pending, setPending] = useState(false);
  const busyRef = useRef(false);
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    if (busyRef.current) return undefined;
    busyRef.current = true;
    setPending(true);
    try {
      return await fn();
    } finally {
      busyRef.current = false;
      setPending(false);
    }
  }, []);
  return [pending, run];
}
