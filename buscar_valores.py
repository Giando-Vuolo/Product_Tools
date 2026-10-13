from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

def buscar_valores_en_archivos(valores: List[str], archivos_o_carpetas: List[str]) -> List[Dict[str, Any]]:
    resultados = []
    archivos_a_procesar = []

    for ruta_str in archivos_o_carpetas:
        ruta = Path(ruta_str)
        
        if ruta.is_file():
            archivos_a_procesar.append(ruta)
        elif ruta.is_dir():
            archivos_a_procesar.extend(ruta.glob("*.txt"))
        else:
            print(f"⚠️ Omitido: No se encontró el archivo o carpeta -> {ruta}")

    for archivo in archivos_a_procesar:
        try:
            contenido = archivo.read_text(encoding='utf-8', errors='ignore')
                
            encontrados = [valor for valor in valores if valor in contenido]
            
            if encontrados:
                timestamp = archivo.stat().st_mtime
                fecha_modificacion = datetime.fromtimestamp(timestamp).strftime('%d/%m/%Y %H:%M:%S')
                
                resultados.append({
                    'archivo': str(archivo),
                    'fecha': fecha_modificacion,
                    'valores': encontrados
                })
                
        except Exception as e:
            print(f"❌ Error procesando {archivo}: {e}")
            
    return resultados

if __name__ == "__main__":
    mis_valores = [
        "WVGZZZ5NZLW342365", "WVWZZZAUZKP502543", "WVGZZZ5NZLW819456", "WVWZZZAUZKW797708", 
        "WVWZZZAUZHW520304", "WVGZZZ5NZKW384083", "WVGZZZ5NZRW050055", "WVGZZZ5NZRW513493", 
        "WVGZZZ1TZMW031046", "WVGZZZ1T1PW026412", "WVWZZZAUZKW795828", "WVWZZZAUZLW503232", 
        "WVWZZZAUZLP530354", "WVWZZZAUZJW677663", "WVWZZZAUZJW673592", "WVWZZZAUZHW528545", 
        "WVWZZZAUZHW578560", "WVWZZZAUZHW518051", "WVWZZZAUZGW560197", "WVWZZZAUZKP552740", 
        "WVWZZZAUZHW549311", "WVWZZZAUZGW573792", "WVWZZZAUZGW585855", "WVWZZZAUZKP544856", 
        "WVWZZZAUZFW607700", "WVWZZZAUZFW560108", "WVGZZZ5NZMW503068", "WVGZZZ1TZMW034874", 
        "WVGZZZ1TZPW016073", "WVWZZZAUZHW580952", "WVWZZZAUZHW572845", "WVWZZZAUZGW515826", 
        "WVGZZZ5NZNW513332", "WVWZZZAUZGW604853", "WVWZZZAUZLP563379"
    ]

    # Archivos de prueba que vamos a crear en el mismo directorio
    mis_rutas = [
        "archivo_prueba_1.txt", 
        "archivo_prueba_2.txt"
    ]

    hallazgos = buscar_valores_en_archivos(mis_valores, mis_rutas)

    print("\n--- RESULTADOS DE BÚSQUEDA ---")
    if not hallazgos:
        print("No se encontró ningún valor en los archivos indicados.")
    else:
        for hallazgo in hallazgos:
            print(f"📁 Archivo: {hallazgo['archivo']}")
            print(f"   🗓️ Fecha de modificación: {hallazgo['fecha']}")
            print(f"   🔍 Valores encontrados: {', '.join(hallazgo['valores'])}\n")
