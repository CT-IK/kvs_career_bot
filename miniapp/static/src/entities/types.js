/**
 * @typedef {'Стажировка' | 'Вакансия'} VacancyKind
 * @typedef {'Офис' | 'Гибрид' | 'Удалёнка'} WorkFormat
 *
 * @typedef {Object} Company
 * @property {string} id
 * @property {string} name
 * @property {string} initial
 * @property {string} brandColor
 * @property {boolean} verified
 *
 * @typedef {Object} Vacancy
 * @property {string} id
 * @property {Company} company
 * @property {string} title
 * @property {string} salary
 * @property {string} metro
 * @property {string} metroColor
 * @property {WorkFormat} format
 * @property {VacancyKind} kind
 * @property {string} [sphere]
 * @property {string[]} [faculties]
 * @property {string} category - primary faculty (first checked), or sphere/fallback text
 * @property {string} experience
 * @property {string} description
 * @property {string} [fullDescription]
 * @property {string[]} requirements
 * @property {string[]} offer
 * @property {string} applyUrl
 *
 * @typedef {Object} CareerEvent
 * @property {string} id
 * @property {string} category
 * @property {string} format
 * @property {string} image
 * @property {string} lead
 * @property {string} title
 * @property {string} date
 * @property {string} place
 * @property {string} description
 * @property {string} deadline
 * @property {string} url
 *
 * @typedef {Object} Education
 * @property {string} university
 * @property {string} program
 * @property {string} period
 *
 * @typedef {Object} Experience
 * @property {string} title
 * @property {string} company
 * @property {string} period
 * @property {string[]} bullets
 *
 * @typedef {Object} ResumeDraft
 * @property {number} step
 * @property {number} totalSteps
 * @property {string} university
 * @property {string} course
 * @property {string} specialty
 *
 * @typedef {Object} Profile
 * @property {string} name
 * @property {string} username
 * @property {string} universityShort
 * @property {string} headline
 * @property {string} location
 * @property {string} relocation
 * @property {string} status
 * @property {string} target
 * @property {string} salary
 * @property {string} email
 * @property {string} phone
 * @property {string} about
 * @property {Education} education
 * @property {string[]} skills
 * @property {Experience[]} experience
 * @property {ResumeDraft} draft
 *
 * @typedef {Object} Route
 * @property {string} name
 * @property {string} path
 * @property {string} [id]
 * @property {URLSearchParams} params
 */

export {};