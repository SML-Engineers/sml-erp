import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

/** The browser's own barcode reader (Chrome on Android and others); no library needed. */
interface Detector {
  detect(source: HTMLVideoElement): Promise<{ rawValue: string }[]>;
}
type DetectorClass = new (options?: { formats: string[] }) => Detector;

function detectorClass(): DetectorClass | null {
  const found = (window as unknown as { BarcodeDetector?: DetectorClass }).BarcodeDetector;
  return found && typeof navigator.mediaDevices?.getUserMedia === "function" ? found : null;
}

/**
 * Scan a QR code or barcode with the phone's camera (P3-08): machines, moulds and material
 * batches. Shown only where the browser can read codes; a handheld scanner types into the
 * field instead.
 */
export default function ScanButton({ label, onScan }: { label: string; onScan: (code: string) => void }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const video = useRef<HTMLVideoElement>(null);
  const Klass = detectorClass();

  useEffect(() => {
    if (!open || !Klass) return;
    let stream: MediaStream | null = null;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const detector = new Klass({ formats: ["qr_code", "code_128", "code_39", "ean_13"] });
    const stop = () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      stream?.getTracks().forEach((track) => track.stop());
    };
    const look = async () => {
      if (stopped || !video.current) return;
      try {
        const codes = await detector.detect(video.current);
        if (codes.length > 0 && !stopped) {
          onScan(codes[0].rawValue.trim());
          stop();
          setOpen(false);
          return;
        }
      } catch {
        // The camera frame was not ready yet; try again.
      }
      timer = setTimeout(look, 300);
    };
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment" } })
      .then(async (s) => {
        stream = s;
        if (stopped || !video.current) return stop();
        video.current.srcObject = s;
        await video.current.play();
        look();
      })
      .catch(() => {
        setError(t("scan.noCamera"));
        setOpen(false);
      });
    return stop;
  }, [open, Klass, onScan, t]);

  if (!Klass) return null;
  return (
    <>
      <button type="button" className="secondary" aria-label={label} onClick={() => setOpen(!open)}>
        {open ? t("scan.stop") : t("scan.scan")}
      </button>
      {open && (
        <div className="scan-view" role="dialog" aria-label={label}>
          <video ref={video} muted playsInline />
        </div>
      )}
      {error && (
        <span className="form-error small" role="alert">
          {error}
        </span>
      )}
    </>
  );
}
