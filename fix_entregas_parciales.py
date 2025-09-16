# fix_entregas_parciales.py - VERSIÓN CORREGIDA SIN CAMPO cantidad_recibida
import os
import sys
import django
from django.db.models import Count

# Agregar el directorio del proyecto al path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Configurar Django con la ubicación correcta de settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'prod_a.settings')

django.setup()

from django.utils import timezone
from almacenes.models import Lote, Material, EntregaParcialLote, EstadoLote


def corregir_entregas_existentes():
    """Crear entregas parciales para lotes que ya tienen materiales pero no entregas registradas"""

    print("Iniciando corrección de entregas parciales...")

    # Buscar lotes que tengan materiales pero no entregas parciales
    lotes_con_materiales = Lote.objects.annotate(
        num_materiales=Count('material')
    ).filter(
        num_materiales__gt=0
    ).exclude(
        id__in=EntregaParcialLote.objects.values_list('lote_id', flat=True)
    )

    print(f"Encontrados {lotes_con_materiales.count()} lotes para corregir")

    if lotes_con_materiales.count() == 0:
        print("No hay lotes que requieran corrección")
        return

    corregidos = 0

    for lote in lotes_con_materiales:
        try:
            # Contar materiales realmente importados
            materiales_count = Material.objects.filter(lote=lote).count()

            if materiales_count > 0:
                print(f"Procesando lote {lote.numero_lote}: {materiales_count} materiales")

                # Obtener cantidad total del lote desde sus detalles
                try:
                    from almacenes.models import LoteDetalle
                    cantidad_total_lote = LoteDetalle.objects.filter(lote=lote).aggregate(
                        total=Count('cantidad')
                    )['total'] or 0

                    if cantidad_total_lote == 0:
                        # Si no hay detalles, asumir que todos los materiales son el total
                        cantidad_total_lote = materiales_count

                    print(f"  Cantidad total estimada del lote: {cantidad_total_lote}")

                except Exception as e:
                    print(f"  No se pudo obtener cantidad total, usando materiales como referencia: {e}")
                    cantidad_total_lote = materiales_count

                # Obtener estado apropiado
                try:
                    if materiales_count >= cantidad_total_lote:
                        estado_entrega = EstadoLote.objects.get(codigo='RECEPCION_COMPLETA', activo=True)
                        print(f"  Estado: COMPLETA ({materiales_count}/{cantidad_total_lote})")
                    else:
                        estado_entrega = EstadoLote.objects.get(codigo='RECEPCION_PARCIAL', activo=True)
                        print(f"  Estado: PARCIAL ({materiales_count}/{cantidad_total_lote})")
                except EstadoLote.DoesNotExist:
                    estado_entrega = EstadoLote.objects.filter(activo=True).first()
                    print(
                        f"  Estado estándar no encontrado, usando: {estado_entrega.nombre if estado_entrega else 'Ninguno'}")

                if estado_entrega:
                    # Crear entrega parcial automática
                    entrega_parcial = EntregaParcialLote.objects.create(
                        lote=lote,
                        numero_entrega=1,
                        fecha_entrega=lote.fecha_recepcion or timezone.now().date(),
                        cantidad_entregada=materiales_count,
                        estado_entrega=estado_entrega,
                        observaciones=f'Entrega automática generada por corrección del sistema - {materiales_count} equipos importados el {timezone.now().date()}',
                        created_by=None
                    )

                    print(f"  Entrega parcial creada: ID {entrega_parcial.id}")

                    # Actualizar número de entrega en los materiales
                    materiales_actualizados = Material.objects.filter(lote=lote).update(numero_entrega_parcial=1)
                    print(f"  Materiales actualizados con número de entrega: {materiales_actualizados}")

                    # Actualizar contador del lote
                    lote.total_entregas_parciales = 1
                    lote.save()

                    corregidos += 1
                    print(f"  ✓ Entrega parcial #1 creada para lote {lote.numero_lote}")
                else:
                    print(f"  ✗ No se pudo crear entrega: no hay estados disponibles")

        except Exception as e:
            print(f"  ✗ Error procesando lote {lote.numero_lote}: {e}")
            import traceback
            traceback.print_exc()

    print(f"Corrección completada: {corregidos} lotes corregidos")


if __name__ == "__main__":
    corregir_entregas_existentes()