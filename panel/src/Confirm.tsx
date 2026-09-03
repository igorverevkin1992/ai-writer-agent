import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

/** Подтверждение необратимого действия: показывает текст (в т.ч. Д-8), ждёт «Да»/«Отмена». */
export type Confirm = (text: string) => Promise<boolean>;

interface Ask {
  text: string;
  resolve: (ok: boolean) => void;
}

/** Собственный модальный диалог вместо window.confirm (аудит 5.7): браузер
 *  не может его подавить и превратить отказ в «тихое ничего». Esc, клик по
 *  фону и «Отмена» — отказ; фокус на «Отмене», чтобы случайный Enter не
 *  подтверждал необратимое. */
export function useConfirm(): [Confirm, ReactNode] {
  const [ask, setAsk] = useState<Ask | null>(null);
  const confirm = useCallback<Confirm>(
    (text) =>
      new Promise((resolve) => {
        setAsk((prev) => {
          prev?.resolve(false); // второй вопрос поверх первого — первый считается отклонённым
          return { text, resolve };
        });
      }),
    [],
  );
  const close = useCallback((ok: boolean) => {
    setAsk((prev) => {
      prev?.resolve(ok);
      return null;
    });
  }, []);
  return [confirm, ask ? <ConfirmDialog text={ask.text} onClose={close} /> : null];
}

export function ConfirmDialog({ text, onClose }: { text: string; onClose: (ok: boolean) => void }) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCloseRef.current(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="modal-backdrop" onClick={() => onClose(false)}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-text"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="confirm-title">Подтверждение</h2>
        <p id="confirm-text">{text}</p>
        <div className="actions">
          <button ref={cancelRef} onClick={() => onClose(false)}>Отмена</button>
          <button className="primary" onClick={() => onClose(true)}>Да</button>
        </div>
      </div>
    </div>
  );
}
