document.addEventListener('DOMContentLoaded', function () {
  function buscarTasa(row) {
    const fechaInput = row.querySelector('[name*="fecha"]');
    const tasaInput = row.querySelector('[name*="tasa_cambio"]');
    if (!fechaInput || !tasaInput) return;
    
    const fecha = fechaInput.value;
    if (!fecha) return;
    
    fetch('/api/tasa/?fecha=' + fecha)
      .then(function(response) { return response.json(); })
      .then(function(data) {
        if (data.tasa && tasaInput.value === '') {
          tasaInput.value = data.tasa;
        }
      })
      .catch(function(err) { console.error('Error obteniendo tasa:', err); });
  }
  
  document.addEventListener('change', function (e) {
    if (e.target.name && (e.target.name.includes('fecha') || e.target.name.includes('moneda'))) {
      const row = e.target.closest('.form-row');
      if (row) buscarTasa(row);
    }
  });
  
  document.addEventListener('focusin', function (e) {
    if (e.target.tagName === 'INPUT' && e.target.name && e.target.name.includes('fecha')) {
      const row = e.target.closest('.form-row');
      if (row) buscarTasa(row);
    }
  });
});
