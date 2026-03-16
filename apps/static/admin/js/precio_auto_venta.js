/**
 * precio_auto_venta.js
 * Auto-rellena precio_unitario y subtotal en DetalleFacturaVenta inline.
 *
 * Cuándo actúa:
 *  1. El usuario selecciona (o cambia) el producto en una fila del inline.
 *  2. El usuario cambia la lista_precio en el formulario principal.
 *  3. Al cargar la página (formulario de edición con filas ya guardadas).
 *
 * Flujo:
 *  - Llama GET /api/precio/?producto_id=X&lista_id=Y
 *  - Actualiza la celda <td class="field-precio_unitario"><p> con el precio
 *    (o muestra "—" si no hay precio aprobado para esa combinación).
 *  - Dispara window.calcularSubtotalFila(row) para recalcular el subtotal.
 *
 * Nota: precio_unitario tiene editable=False en el modelo; Django lo muestra
 * como <p> readonly, no como <input>. El guardado real ocurre en el servidor
 * al llamar a emitir() que lee el precio desde DetalleLista aprobado.
 */
document.addEventListener('DOMContentLoaded', function () {

  function getListaId() {
    var sel = document.getElementById('id_lista_precio');
    return sel ? sel.value : '';
  }

  function actualizarPrecioFila(row) {
    // Busca el <select name="detalles-N-producto"> dentro de la fila
    var productoSel = row.querySelector('select[name$="-producto"]');
    if (!productoSel || !productoSel.value) return;

    var listaId = getListaId();
    if (!listaId) return;

    var precioEl = row.querySelector('.field-precio_unitario p');
    if (!precioEl) return;

    fetch('/api/precio/?producto_id=' + productoSel.value + '&lista_id=' + listaId)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.precio) {
          precioEl.textContent = data.precio;
        } else {
          precioEl.textContent = '\u2014'; // — sin precio aprobado
        }
        // Recalcular subtotal de esta fila usando calcular_subtotal.js
        if (typeof window.calcularSubtotalFila === 'function') {
          window.calcularSubtotalFila(row);
        }
      })
      .catch(function (err) {
        console.error('precio_auto_venta: error obteniendo precio:', err);
      });
  }

  function actualizarTodos() {
    document.querySelectorAll('.form-row:not(.empty-form)').forEach(actualizarPrecioFila);
  }

  // Evento delegado: producto cambia en cualquier fila del inline
  document.addEventListener('change', function (e) {
    if (!e.target.name) return;

    // Nombre del campo producto en inline: "detalles-0-producto", etc.
    if (e.target.name.endsWith('-producto')) {
      var row = e.target.closest('tr') || e.target.closest('.form-row');
      if (row) actualizarPrecioFila(row);
    }

    // Lista de precios cambia en el formulario principal
    if (e.target.id === 'id_lista_precio') {
      actualizarTodos();
    }
  });

  // Carga inicial: útil al editar una factura existente
  actualizarTodos();
});
