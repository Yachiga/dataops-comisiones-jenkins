-- Consulta de extracción usada por el pipeline (Python y actividad Copy de ADF)
SELECT empleado_id, tip_documento, num_documento, nom_empleado, ape_empleado,
       cod_cargo, cod_departamento, mnt_salario, mnt_tope_comision
FROM rrhh.empleado;

-- Verificación posterior: empleados del CSV que no existen en la tabla
-- (ejecutar tras cargar el CSV a una tabla temporal tmp_comision)
-- SELECT c.empleado_id FROM tmp_comision c
-- LEFT JOIN rrhh.empleado e USING (empleado_id) WHERE e.empleado_id IS NULL;
