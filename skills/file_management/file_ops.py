# skills/file_management/file_ops.py
import os
import shutil

def manage_files(action: str, path: str, content: str = "", new_path: str = "") -> str:
    try:
        if action == "create":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully created file at {path}"

        if action == "read":
            if not os.path.exists(path):
                return f"File not found: {path}"
            with open(path, "r", encoding="utf-8") as f:
                return f.read()

        if action == 'mkdir':
            target = path or '.'
            os.makedirs(target, exist_ok=True)
            return f"✅ Created directory: {target}"

        if action == 'list':
            target = path or '.'
            if not os.path.exists(target):
                return f"❌ Path not found: {target}"
            if os.path.isfile(target):
                return f"❌ Path is a file, not a directory: {target}"
            entries = sorted(os.listdir(target))
            if not entries:
                return f"(empty directory) {target}"
            return "\n".join(entries)

        if action == 'delete':
            if not os.path.exists(path):
                return f"❌ Path not found: {path}"
            if os.path.isdir(path):
                shutil.rmtree(path)
                return f"✅ Directory removed: {path}"
            else:
                os.remove(path)
                return f"✅ File removed: {path}"

        if action == 'move':
            if not os.path.exists(path):
                return f"❌ Source not found: {path}"
            os.makedirs(os.path.dirname(new_path) or '.', exist_ok=True)
            shutil.move(path, new_path)
            return f"✅ Moved {path} -> {new_path}"

        if action == 'copy':
            if not os.path.exists(path):
                return f"❌ Source not found: {path}"
            os.makedirs(os.path.dirname(new_path) or '.', exist_ok=True)
            if os.path.isdir(path):
                shutil.copytree(path, new_path)
            else:
                shutil.copy2(path, new_path)
            return f"✅ Copied {path} -> {new_path}"

        if action == 'save_text_pdf':
            output_path = path
            os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

            def _pdf_escape(value: str) -> str:
                return value.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)').replace('\r', '').replace('\n', '\\n')

            lines = content.splitlines() if content else ['']
            content_lines = []
            y = 760
            for line in lines:
                content_lines.append(f"BT /F1 12 Tf 50 {y:.0f} Td ({_pdf_escape(line)}) Tj ET")
                y -= 18
                if y < 40:
                    break

            page_stream = "\n".join(content_lines).encode('latin-1')
            objects = []
            objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
            objects.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
            objects.append(
                b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
            )
            objects.append(b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")
            objects.append(
                b"5 0 obj\n<< /Length %d >>\nstream\n" % len(page_stream) + page_stream + b"\nendstream\nendobj\n"
            )

            pdf_bytes = b"%PDF-1.4\n"
            xref_offsets = [len(pdf_bytes)]
            for obj in objects:
                pdf_bytes += obj
                xref_offsets.append(len(pdf_bytes))

            xref_start = len(pdf_bytes)
            pdf_bytes += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
            for offset in xref_offsets[:-1]:
                pdf_bytes += f"{offset:010d} 00000 n \n".encode('latin-1')

            pdf_bytes += (
                b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n" % (len(objects) + 1)
                + str(xref_start).encode('latin-1')
                + b"\n%%EOF\n"
            )

            with open(output_path, 'wb') as f:
                f.write(pdf_bytes)
            return f"✅ Saved PDF to {output_path}"

        return "Invalid action"
    except Exception as e:
        return f"File operation failed: {str(e)}"


def save_text_pdf(path: str, text: str = "", title: str = "Document") -> str:
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)

        def _pdf_escape(value: str) -> str:
            return value.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)').replace('\r', '').replace('\n', '\\n')

        lines = text.splitlines() if text else ['']
        content_lines = []
        y = 760
        for line in lines:
            content_lines.append(f"BT /F1 12 Tf 50 {y:.0f} Td ({_pdf_escape(line)}) Tj ET")
            y -= 18
            if y < 40:
                break

        page_stream = "\n".join(content_lines).encode('latin-1')
        objects = []
        objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
        objects.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
        objects.append(
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
        )
        objects.append(b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")
        objects.append(
            b"5 0 obj\n<< /Length %d >>\nstream\n" % len(page_stream) + page_stream + b"\nendstream\nendobj\n"
        )

        pdf_bytes = b"%PDF-1.4\n"
        xref_offsets = [len(pdf_bytes)]
        for obj in objects:
            pdf_bytes += obj
            xref_offsets.append(len(pdf_bytes))

        xref_start = len(pdf_bytes)
        pdf_bytes += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        for offset in xref_offsets[:-1]:
            pdf_bytes += f"{offset:010d} 00000 n \n".encode('latin-1')

        pdf_bytes += (
            b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n" % (len(objects) + 1)
            + str(xref_start).encode('latin-1')
            + b"\n%%EOF\n"
        )

        with open(path, 'wb') as f:
            f.write(pdf_bytes)
        return f"✅ Saved PDF to {path}"
    except Exception as e:
        return f"Failed to save PDF: {str(e)}"
