from flask import Flask, request, send_file, jsonify  
import subprocess  
import tempfile  
import os  
import logging
import sys

logging.basicConfig(stream=sys.stdout, level=logging.DEBUG) 

app = Flask(__name__)  

# Set up logging to stdout so Docker logs capture it  
logging.basicConfig(level=logging.DEBUG)  

@app.route("/convert/to-md", methods=["POST"])  
def to_md():  
    in_path = out_path = None  
    try:  
        if "file" not in request.files:  
            return jsonify({"error": "No file part"}), 400  

        uploaded = request.files["file"]  
        name, ext = os.path.splitext(uploaded.filename)  
        ext = ext.lower()  # including the “.”  

        # 1) Write upload to temp  
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:  
            uploaded.save(tmp)  
            tmp.flush()  
            in_path = tmp.name  

        # 2) Prepare output path  
        out_path = in_path + ".md"  

        # 3) Choose converter  
        if ext in (".pptx", ".pdf"):  
            # markitdown example.pdf -o example.md  
            cmd = ["markitdown", in_path, "-o", out_path]  
        else:  
            # let Pandoc autodetect based on extension (docx, odt, html, etc.)  
            cmd = ["pandoc", in_path, "-t", "commonmark", "-o", out_path]  

        logging.debug(f"Running converter: {' '.join(cmd)}")  
        proc = subprocess.run(cmd, capture_output=True, text=True)  

        if proc.returncode != 0:  
            logging.error(f"Conversion failed: {proc.stderr.strip()}")  
            return jsonify({"error": proc.stderr.strip() or "Conversion failed"}), 500  

        # 4) Sanity check  
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:  
            logging.error("No markdown output generated")  
            return jsonify({"error": "No markdown output"}), 500  

        # 5) Stream back the .md  
        return send_file(  
            out_path,  
            mimetype="text/markdown",  
            as_attachment=True,  
            download_name="converted.md"  
        )  

    except Exception as e:  
        logging.exception("Unhandled exception in to_md")  
        return jsonify({"error": str(e)}), 500  

    finally:  
        # cleanup temp files  
        for p in (in_path, out_path):  
            try:  
                if p and os.path.exists(p):  
                    os.unlink(p)  
            except OSError:  
                pass   

@app.route("/convert/from-md", methods=["POST"])  
def from_md():  
    """  
    Convert an uploaded Markdown file to DOCX, PDF, or PPTX using Pandoc.  
    """  
    in_path = None  
    out_path = None  
    try:  
        if "file" not in request.files:  
            logging.error("No file part in request")  
            return jsonify({"error": "No file part"}), 400  

        file = request.files["file"]  
        target = request.args.get("target", "docx").lower()  
        ext = "." + target  

        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as in_f:  
            file.save(in_f)  
            in_f.flush()  
            in_path = in_f.name  

        out_path = in_path + ext  
        result = subprocess.run(  
            ["pandoc", in_path, "-o", out_path, "--log=/app/log.txt"],  
            capture_output=True, text=True  
        )
        if result.returncode != 0:  
            logging.error(f"Pandoc conversion failed: {result.stderr}")  
            return jsonify({"error": result.stderr or "Pandoc conversion failed."}), 500  

        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:  
            logging.error("Pandoc did not produce output.")  
            return jsonify({"error": "Pandoc did not produce output."}), 500  

        return send_file(out_path, mimetype="application/octet-stream", as_attachment=True, download_name=f"converted{ext}")  
    except Exception as e:  
        logging.exception("Exception during conversion from markdown")  
        return jsonify({"error": str(e)}), 500  
    finally:  
        if in_path and os.path.exists(in_path):  
            try:  
                os.unlink(in_path)  
            except Exception:  
                pass  
        if out_path and os.path.exists(out_path):  
            try:  
                os.unlink(out_path)  
            except Exception:  
                pass  

if __name__ == '__main__':  
    app.run(host="0.0.0.0", port=5000)