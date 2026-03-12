document.addEventListener('DOMContentLoaded', function () {
  function calcularSubtotales() {
    // Compras: campos cantidad y costo_unitario
    document.querySelectorAll(
      '.form-row:not(.empty-form)'
    ).forEach(function (row) {
      const cantidad = parseFloat(
        row.querySelector('[name*="cantidad"]')?.value
      ) || 0;
      const costo = parseFloat(
        row.querySelector(
          '[name*="costo_unitario"],[name*="precio_unitario"]'
        )?.value
      ) || 0;
      const subtotalEl = row.querySelector(
        '[name*="subtotal"], .field-subtotal p'
      );
      if (subtotalEl) {
        const resultado = (cantidad * costo).toFixed(2);
        if (subtotalEl.tagName === 'INPUT') {
          subtotalEl.value = resultado;
        } else {
          subtotalEl.textContent = resultado;
        }
      }
    });
  }

  // Ejecutar al cambiar cualquier campo de cantidad o precio
  document.addEventListener('input', function (e) {
    if (
      e.target.name && (
        e.target.name.includes('cantidad') ||
        e.target.name.includes('costo_unitario') ||
        e.target.name.includes('precio_unitario')
      )
    ) {
      calcularSubtotales();
    }
  });

  // Ejecutar al cargar por si hay valores precargados
  calcularSubtotales();
});
