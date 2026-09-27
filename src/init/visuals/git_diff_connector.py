"""Conector entre el panel Git Diff y la herramienta git_diff."""

import subprocess
from pathlib import Path


def get_git_diff(repo_path: str) -> list[dict]:
    """
    Obtiene el diff del repositorio Git actual.
    
    Args:
        repo_path: Ruta al repositorio Git
        
    Returns:
        Lista de dicts con la información del diff
    """
    diffs = []
    
    try:
        # Ejecutar git status para obtener los archivos modificados
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        
        lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
        
        for line in lines:
            if not line:
                continue
            
            # Formato de git status --porcelain:
            # M archivo (modificado)
            # A archivo (añadido)
            # D archivo (eliminado)
            
            status = line[0]
            file_path = line[2:]  # Saltamos los primeros 2 caracteres
            
            if status in ['M', 'A', 'D', 'R', 'C', 'U']:
                # Obtener el diff del archivo
                diff_result = subprocess.run(
                    ['git', 'diff', '--no-color', '--unified=3', file_path],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    check=False  # No fallar si no hay cambios
                )
                
                if diff_result.returncode == 0 or not diff_result.stdout.strip():
                    lines_diff = []
                    
                    if diff_result.stdout.strip():
                        for line in diff_result.stdout.split('\n'):
                            if line.startswith('+') and not line.startswith('+++'):
                                lines_diff.append({'type': 'added', 'text': line[1:]})
                            elif line.startswith('-') and not line.startswith('---'):
                                lines_diff.append({'type': 'deleted', 'text': line[1:]})
                            elif line.startswith(' ') or line.startswith('\\'):
                                lines_diff.append({'type': 'context', 'text': line.strip()})
                    
                    diffs.append({
                        'file': file_path,
                        'status': status.lower(),
                        'lines': lines_diff
                    })
    
    except subprocess.CalledProcessError as e:
        # Ignorar errores de Git (no es un repositorio o no hay cambios)
        pass
    
    return diffs


def get_git_status(repo_path: str) -> dict:
    """
    Obtiene el estado del repositorio Git.
    
    Args:
        repo_path: Ruta al repositorio Git
        
    Returns:
        Dict con información del estado del repositorio
    """
    status = {
        'is_repo': False,
        'modified_files': [],
        'added_files': [],
        'deleted_files': []
    }
    
    try:
        result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.returncode == 0 and result.stdout.strip():
            status['is_repo'] = True
            lines = result.stdout.strip().split('\n')
            
            for line in lines:
                if not line:
                    continue
                
                status_char = line[0]
                file_path = line[2:]
                
                if status_char == 'M':
                    status['modified_files'].append(file_path)
                elif status_char == 'A':
                    status['added_files'].append(file_path)
                elif status_char == 'D':
                    status['deleted_files'].append(file_path)
    
    except Exception:
        pass
    
    return status
